# Tasks: The split: the core and the orchestrator

**Input**: the design documents under `specs/020-core-orchestrator-split/`: [plan.md](plan.md),
[spec.md](spec.md) (clarified 2026-10-29, nothing asked), [research.md](research.md) (§1
verified at plan, §2 decisions R-01…R-24, §3 the 3.0.0 amendment drafted, §4 owed at
implement, §5 appended by the runs), [data-model.md](data-model.md) (§1–§12),
[contracts/README.md](contracts/README.md), [quickstart.md](quickstart.md); the
[brief](brief.md); Constitution 2.3.0, amended to 3.0.0 by the operator at T002;
[D-065](../../docs/decisions.md#d-065) and [D-066](../../docs/decisions.md#d-066), appended
at feature-open; [D-040](../../docs/decisions.md#d-040), [D-045](../../docs/decisions.md#d-045)
to [D-048](../../docs/decisions.md#d-048), [D-051](../../docs/decisions.md#d-051) to
[D-053](../../docs/decisions.md#d-053), [D-057](../../docs/decisions.md#d-057) to
[D-062](../../docs/decisions.md#d-062), [D-064](../../docs/decisions.md#d-064).

**Tests**: requested. The brief's Exit, the spec's SC-001–SC-011 and quickstart §1–§8 name
each tier's cases, and each is a task below. Every format test validates against the
contract file under `contracts/`, and every earlier format against its frozen copy under
`testdata/contracts/016-probes/` (T004). **What must not move** (FR-033): CTM `2`, snapshot
`2`, bundle `6`, probes `1`, the probe package `0.1`, PSP `0.7` and both shipped packages,
the vendored library under `schema/dcim/`, the template and its query under `infrahub/`,
`.infrahub.yml` but for its comment on the checks, `fylgja-twin`'s `timeout` 4260, the
step's and verify's rules, the seven replay histories under `internal/provision/testdata/`,
the API at `1` and findings at `1`, the four goldens (`c70589c3…`, `10099944…`, `44ac283f…`,
`5222063b…`), `testdata/snapshot/*`'s ids and `testdata/ctm/*`, the fixture's snapshot id
`0940db93…` and compiled id `c3872f5c…`, and nothing on Infrahub's `main` or in either
fixture branch. **The adapter is held to the Go reader byte for byte** (T021) and the three
documents' renderers to goldens captured from the Go implementation (T003, T022) **before
the Go code goes** (Phase 8): a run that removes before it has compared has broken the
feature. Any run that changes `testdata/golden/` has broken it too, and the loop will stop.

**Organization**: the plan's "Order of the work". Phase 2 lands what every later phase
stands on: the goldens captured from the running Go build before any code changes, the
016 shapes frozen, the five new identifiers, and the roadmap reconciled (the route's first
documents task, FR-032). Then the core's shape (US4, US5, US2; Phase 3), the orchestrator's
toolchain (US7; Phase 4), the adapter's port, module by module, each Go contract test's
assertions carried over and the whole compared with the Go reader (US3; Phase 5), the
documents, the core client, the record, the six flows and `fylgja-cli` (US1, US3, US5, US6;
Phase 6), the checks, the host's scripts and tier 3's script (US1; Phase 7), the removal
with the boundary test and the contracts' prose (US2, US7; Phase 8), the documents (US7;
Phase 9), the operator's import (Phase 10), the host and the hand scenarios, live (Phase
11), the tiers (Phase 12) and the records (Phase 13). The loop runs the pure gates after
every implement run, so every run must leave the tree green: `make build`, static, `make
test` (Go then `pytest -m 'not contract'` once T013 lands), `make lint` (golangci-lint with
tags `contract,fixture,e2e`, so every tagged test must compile after every run; `ruff` once
T013 lands).

**Already done before this file** (brief, Operator steps; plan; research §1 and §3): 016
merged and pushed (`origin/main` at `3a5aa37`); D-065 and D-066 appended and feature-open's
commit (`07b3d7f`) pushed, so no push is owed during the chain; Prefect 3.9.0 verified on
the host (research §1.1–§1.5) and the tree read (§1.6); the 3.0.0 amendment drafted
(research §3.2), not yet appended; the roadmap **not** yet reconciled (T006). No operator
task is owed before Phase 2 but T002, at `analyze`.

**Decisions this file takes, against or beyond the plan's text** (for `analyze` to settle):

- **The constitution's amendment is T002, at `analyze`, not in the removal phase** where
  the plan's order (item 7) places it. From Phase 4 on the tree holds a Python project,
  which Principle I as 2.3.0 words it forbids, and every later run's Constitution Check
  must read 3.0.0's text; 016's T002 set the pattern.
- **The goldens are captured at the baseline (T003), before any Go change**, from the
  processes the host already runs from 016's close, which are this code: `stage list`'s
  twin row reads `twin.json` `11`'s stage block, which T011 removes, and no rebuild is
  needed. The plan's order has the capture after the core's shape.
- **The Python tier 2 seeds Infrahub through `cmd/fylgja-fixture` as a subprocess**, the
  Go test tool FR-016 keeps, gaining a flag wherever a ported Go test's seeding has none
  (T020); `internal/testsupport` is not ported.
- **`rehearsal.schema.json` and `stages.schema.json` stay in `contracts/` with their
  `$id`s**; "moved" (R-13, data-model §12) is ownership: `contracts/orchestrator.md`
  describes them and `api.md` stops.
- **`make sdl`, `make generate`, `schema/infrahub.graphql`, `internal/intent/genqlient.yaml`
  and CI's `go generate … && git diff --exit-code` step go with the reader** (T035): the
  reader was genqlient's one client. The plan does not say.
- **`orchestrator/.venv` joins the loop's lane seed list** (`seed_worktree` in
  `scripts/converge-loop.sh`, T013), so a lane's `make test` finds `pytest`; Run 12, which
  makes the venv on the host, is never laned.
- **Tier 2's create from the fixture is the core's dry run** (`twin-create` with
  `dry_run`, T028), which names the bundle `c3872f5c…` without booting a twin, since no
  twin boots while tier 2 runs; the built twin is tier 3's and quickstart §5's.
- **T039, the checks' push and import, sits after the documents (Phase 10)**, the latest
  point its dependents (T042, T043) allow: once imported, every proposed change opened on
  this Infrahub runs checks that need the override's new variables, which the task workers
  carry only after T040's `up -d`, so nothing that opens a proposed change runs between.

**Settled by `analyze` (2026-10-29, headless)**: the eight taken as written, the fourth
and the seventh carried into the plan artifacts and the spec (research R-13, data-model
§6, §8 and §12, contracts/README.md; FR-028 and US3's Independent Test); the three
`[operator]` tasks kept with their reasons; the six lane marks held, Run 4's `Read first:`
losing `data-model.md` so Run 5 ∥ Run 4 reads disjoint sets; T007's `Service` placed in
`client.go`; the record's trust read from `show.record.snapshot_id`; T047 made pure (the
final build's restart a live session's or the operator's); `Runner` added to the glossary
terms (T038, FR-031) and the spec's "the platform's server and worker" made "its runner".
T002's question the operator answered with option 1, the draft approved as written (T002's note).

**Tags**: `[operator]` marks a task that needs the operator and could not be done before
the chain, with its reason on its line; `[live]` marks a task that needs the development
host's server or worker restarted from this tree, a twin, a hand scenario, the whole
contract tier beside the platform on the bridge, or the end-to-end tier. A single tier-2
test a task names (T015's id test, T020, T021, T028) is not `[live]`: the loop's sessions
hold Infrahub's address and token and run it. A loop run commits its own work; a hand run
leaves it for the operator to commit. A session never pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[tag]**: `[operator]` or `[live]`, as above; converge adds `[behaviour]` and `[pin]`.
- **[P]**: can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US7, from spec.md.
- Every task names the files it edits or reads, so the route's `Read first:` and lanes can
  be derived from the tasks.

---

## Phase 1: Setup (the baseline and the amendment)

**Purpose**: confirm the tree's gates pass on this branch before anything changes, so any
later failure is this feature's own; read, writing nothing, what the host and Infrahub hold;
then the constitution amended at `analyze`.

- [X] T001 Run the pure gates and read the tree's state, writing nothing: `make build` (static), `make test` (uncached, its wall time against the 65 s budget), `make lint`, `go vet -tags contract,fixture,e2e ./...`; `git status` clean on `020-core-orchestrator-split` at `d953841` or later; quickstart §0's reads: `free -m`, `pgrep -x fylgja -a` (the worker and the server, their `/proc/<pid>/exe` not `(deleted)`), Infrahub's eight containers healthy, `ss -ltn | grep 4200` empty, `local/command-log/pending.jsonl` empty; `docker image inspect alpine:3.24.2 ceos:4.32.0.2F ghcr.io/nokia/srlinux:24.7.1 --format '{{.Id}}'`; the counts `CoreProposedChange`, `FylgjaStage`, `FylgjaProbe` 0 on `main` and `Branch` listing `main` and `fylgja-fixture` alone. Report each in this task's note.
  - **Note (Run 1, 2026-10-29)**: the tree: `git status` clean on `020-core-orchestrator-split` at `2ece00b` (`d953841` an ancestor); `origin/main` at `07b3d7f`, past `3a5aa37`; `id="d-066"` once in `docs/decisions.md`. The gates: `make build` static (`statically linked`, `vcs.revision=2ece00b`); `make test` green uncached (`go clean -testcache` first) in 58.0 s wall against the 65 s budget at a load of 2.8–3.1, `internal/cli` 42.6 s, `internal/lab` 12.3 s, `internal/provision` 9.8 s; `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean. The host: `free -m` 17,135 MiB available of 31,065, swap unused; `pgrep -x fylgja` the worker (`3692672`) and the server (`3692794`, both listens), both on `195af3a`'s build (016's merge; no Go, `go.mod`, `go.sum`, `contracts/` or `probes/` change from it to `2ece00b`), their `/proc/<pid>/exe` live before the build and `(deleted)` after it, since the build's VCS stamp (`2ece00b`) replaced the binary with the same code: this run starts and stops no process, so T003 restarts both from this tree first, as it says; Infrahub's eight containers up 44 h, the six with a health check `healthy`, the two task workers having none; `ss -ltn` holds no 4200; `local/command-log/pending.jsonl` absent; no `clab-` container. The images: `alpine:3.24.2` `sha256:294b683c…`, `ceos:4.32.0.2F` `sha256:2b2efd54…`, `ghcr.io/nokia/srlinux:24.7.1` `sha256:171ec8d4…`. Infrahub on `main`: `CoreProposedChange`, `FylgjaStage`, `FylgjaProbe`, `CoreChangeThread` and `CoreUserValidator` 0; `Branch` `main` and `fylgja-fixture` alone; schema hash `8a4f3bee…`; `CoreReadOnlyRepository` `fylgja` alone at `842c893`. Nothing written. One correction for T003: its `d1b0786` is not the running build's revision, `195af3a` is, and Go has moved since `d1b0786` (016's converge passes); the comparison holds against `195af3a`.

- [X] T002 [operator] Amend the constitution to 3.0.0 as research §3.2 drafts it and as `analyze` takes it, since the text is the plan's and the constitution is amended only by the operator citing an entry (`CLAUDE.md`, Workflow): `.specify/memory/constitution.md` (the Sync Impact Report line, the preamble, I, III, VI, VIII, IX, X, XI, Development Workflow's repository gate and three-tier line, the version and the date) and `.specify/templates/plan-template.md` (its Constitution Check names 3.0.0; rows I, III, VI, VIII, IX and XI read the amended text); `plan.md`'s Constitution Check row I then reads PASS under 3.0.0. Nothing else.
  - **Note (analyze, 2026-10-29, headless)**: the operator answered option 1: the draft approved as written. To apply at Run 2, exactly research §3.2's lines, plus the two things the draft does not name: `CLAUDE.md`'s "(2.3.0)" is T046's to move, and the Gate Adjustments' "four layers" count is unchanged, since no layer is added. Nothing is left to decide.
  - **Note (Run 2, 2026-10-29)**: applied as research §3.2 drafts it. `.specify/memory/constitution.md` at 3.0.0, last amended 2026-10-29: the Sync Impact Report's 3.0.0 entry, citing D-065 and D-066, above 2.3.0's; the preamble's two deployables (D-065), the twin's description its own sentence after it; I titled "Go, End to End, for the Core", binding the core and freeing the orchestrator, rationale D-065 added; III's reader an adapter of the orchestrator that writes a snapshot, the core's one input (D-061), rationale D-065 added; VI's last sentence the adapter's snapshot held by the orchestrator (D-066); VIII's provisioning in the core, and the orchestrator driving the core through the API and starting none of its workflows; IX's orchestrator state and neither deployable's database; X's log line in either deployable; XI's orchestrator a client and a check inside Infrahub its client, the core's CLI, rationale D-065 added; Development Workflow's repository gate (D-065 added) and three-tier line. The Gate Adjustments unchanged, "four layers" with them; VIII's and IX's rationale lines unchanged, as the draft leaves them; paragraphs I touched re-wrapped. `.specify/templates/plan-template.md`'s Check names 3.0.0 and its rows I, III, VI, VIII, IX and XI read the amended text; X's row unchanged, as the task names it not. `plan.md`'s row I reads PASS under 3.0.0, its gate "Go only for the core"; its preamble line and Complexity Tracking left as the record of 2.3.0's violation. `CLAUDE.md`'s "(2.3.0)" left for T046.

---

## Phase 2: Foundational

**Purpose**: what every later phase stands on: the goldens of the three documents captured
from the Go build before it changes, the 016 shapes frozen, the core's five new
identifiers, and the roadmap reconciled.

- [X] T003 [live] Capture the goldens (R-14, FR-023, SC-007) on the processes the host runs from 016's close (this code; compare `bin/fylgja --version`'s `vcs.revision` with `d1b0786`'s content: no Go has changed since; if the running build differs, rebuild and restart both processes from this tree first, as `CLAUDE.md` says), `free -m` read first, no tier running: a throwaway proposed change on `fylgja-test-golden-<pid>` through `go run -tags fixture ./cmd/fylgja-fixture -branch … -propose`, `-stage seeded`, `-add-link`, `-stage third-link`, a third stage on a further change, then `bin/fylgja stage list --branch … --json` and without `--json`, `stage plan --branch … --json` and text, `twin create --stage …/seeded` then `stage list` again (the twin's row) then `twin destroy`, then the proposed change marked ready and `twin rehearse --branch … --json` (the document) with the posted thread's comment read back by GraphQL (the markdown, `CoreChangeThread`/`CoreThreadComment`); the text form of the rehearsal rendered from the captured JSON by a throwaway Go test over `internal/findings`' renderer, deleted after (a second live rehearsal only if that fails). Save under `orchestrator/tests/golden/` as `stages.json`, `stages.txt`, `stages-with-twin.json`, `stages-with-twin.txt`, `plan.json`, `plan.txt`, `rehearsal.json`, `rehearsal.txt`, `rehearsal.md`, with a `README.md` naming the branch, the proposed change's id, each stage's `at` and snapshot and bundle ids, and the fixture tool's flags used; then `fylgja-fixture -branch … -delete` and the counts of T001 read again. Record the ids and the wall times in research §5. Commit nothing under `testdata/`.
  - **Note (Run 3, 2026-10-29)**: the processes already ran `96d38d8` (the same code as `195af3a`), live; rebuilt and restarted from this tree anyway and verified (both exes live, both logins and every `INFRAHUB_*` name set, the start-up reports whole, the bridge listen). On `fylgja-test-golden-41263`, change `18e3127c-025b-f488-33be-c5158cf576c3`: `seeded`, `-add-link`, `third-link`, then the further change 015's `bad-port` (`-add-interface n1:ethernet-1/99 -generate`), so the rehearsal fails at a push and carries every verdict and the reproduce lines. Two departures from the line, each with its reason in research §5.1. The rehearsal was asked once through the API under `render: "markdown"`, whose last frame holds the document, its text and the markdown, since `twin rehearse` posts no thread and a check's re-run would be a second rehearsal whose answer is not kept. Its markdown was then posted by the check's own `post_comment`, and the `CoreThreadComment` read back equals it byte for byte. The text is two streams, so beside the nine files are `plan.stderr.txt`, `rehearsal.stderr.txt` (`WriteText`), `rehearsal.out.txt` (stdout whole) and `rehearsal.full.md` (`Markdown`'s whole form, the live one being shortened past 4,092 bytes), each in the golden README. The throwaway test (deleted) rendered `rehearsal.txt`, the findings and both markdowns from `rehearsal.json` and `plan.json`'s steps, and each equals the live frames. The state root is read `<state-root>` in two files, the one edit, for the hygiene bar. The rehearsal ended `nonconforming`, 74.5 s of 2,580 s. Infrahub and the host were left as T001 found them. Ids and times are in research §5.1.

- [X] T004 [P] Freeze the 016 shapes (data-model §1, §2, §12): copy `contracts/api.schema.json`, `twin.schema.json` (`11`) and `findings.schema.json` as `git show 3a5aa37:contracts/<name>` into `internal/server/testdata/contracts/016-probes/`, `internal/cli/testdata/contracts/016-probes/`, `internal/lab/testdata/contracts/016-probes/` (twin alone) and `internal/findings/testdata/contracts/016-probes/` (findings alone); add a `contract016 = "016-probes"` constant beside each `contract019` (`internal/server/helpers_test.go`, `internal/cli/create_test.go`, `internal/lab/twin_test.go`, `internal/findings/snapshot_test.go`); move `frozenContractCopies` in `internal/findings/frozen_contracts_test.go` (72) by the count; `TestFrozenContractCopiesAgree` passes. Record the count and any copy not made, with why, in this task's note.
  - **Note (Run 4, 2026-10-29)**: 8 copies made, none left out, each byte-equal to `contracts/` (no contract has moved since `3a5aa37`): `api`, `twin` and `findings` under `internal/server/` and `internal/cli/`, `twin` under `internal/lab/`, `findings` under `internal/findings/`; `frozenContractCopies` 72 → 80. Each constant is read, so none is dead (lint's `unused`) and each copy is exercised now: `validateM10Document` in `internal/server` and `internal/cli` validates every document against 016's findings copy as built (no null loss taken out); `TestA016DocumentIsUnchanged` in `internal/findings`; `TestRecord11RecordsAHost` reads its record against 016's `twin` copy (`internal/lab/twin_test.go` had no `contract019`, only the literal, so its `contract016` sits under `twinSchemaOf`). The `api` and `twin` copies under `internal/server/` and `internal/cli/` wait for T007–T011 and are held by `TestFrozenContractCopiesAgree`. One fix the copies needed: a block a frozen copy lacks was read from the next frozen directory by name, and `016-probes` sorts before `017-dcim-reader` though 016 closed after 019, so 016's findings copy would have been compiled beside 017's blocks; `laterContract` (`internal/server`, `internal/cli`) and `compileFeatureFindingsSchema` (`internal/findings`) now take the directories in the order the features closed (`closeOrder`, 016 after 019), which changes nothing for 017–019 today. Each findings copy was broken by hand once and its package's tests failed naming 016's contract, then restored.

- [X] T005 [P] The core's identifiers (data-model §11, R-19) in `internal/findings/finding.go` and `finding_test.go`: `run.detached` (info, step `start`, message `run <workflow_id> <run_id> started; read it with fylgja run read`), `run.unknown` (error, exit 1, naming the identity), `run.cancel.requested` (info), `run.ended` (error, exit 1), `run.flags.conflict` (error, exit 1, `dry_run` beside `detach`); the operations `run.read`, `run.interrupt`, `twin.diff` in `contracts/findings.schema.json`'s enum and the rules in its pattern test; nothing retired yet (T035).
  - **Note (Run 5, 2026-10-29)**: the five rules are constants in `internal/findings/finding.go` (`RuleRunDetached`, `RuleRunUnknown`, `RuleRunCancelRequested`, `RuleRunEnded`, `RuleRunFlagsConflict`), each commented with its severity, exit, step, object and cause, and appended to `finding_test.go`'s rule table; the pattern test reads them from the syntax tree, so it holds them with no edit. `run.unknown`, `run.cancel.requested` and `run.ended` carry no step, since the data model names none and neither operation is a step of a run; `run.flags.conflict`'s object is `dry_run`, at step `start`. The three operations are `OpRunRead`, `OpRunInterrupt` and `OpTwinDiff` in `render.go`, where the `Op*` constants live, and in `contracts/findings.schema.json`'s enum; `TestOperationConstantsMatchTheContract` names them, and a new `TestTheRunRulesRenderValidDocuments` holds a document of each rule, and an empty `twin.diff`, to the current contract with its exit. One file beyond the task's: `internal/api/wire_test.go`'s `TestOperationsAreTheContractsAndTheirPaths` compares `api.Operations` with the enum exactly, so it now leaves out a `notYetServed` list of the three, each asserted absent from `Operations`; T007 drops `run.read` and `run.interrupt` from it and T010 `twin.diff`, as each serves its operation. Nothing retired (T035).

- [X] T006 [P] Reconcile the roadmap (R-24, FR-032, US7 scenario 5) in `docs/roadmap.md`: F-027's table row gains its description (the orchestrator on Prefect 3.9.0 in Python, the Infrahub reader ported to Python as its first adapter, the core narrowed to the snapshot), its dependency on F-014 and the estimate `24–36` in place of `—` and "its brainstorm's"; Release 0.3's total moves from `25–39, plus F-027's once briefed` to `49–75`; item 5 links to `specs/020-core-orchestrator-split/`; F-027's paragraph names this feature. The production shape's "a direction, not a decision" line is T045's, not this task's.

**Checkpoint**: the tree is green and nothing user-visible has changed; the goldens are in
the tree, so the Go renderers may now change or go.

---

## Phase 3: User Stories 4, 5 and 2 — the core's shape (Priority: P2, P2, P1)

**Goal**: the core gains `detach`, `run.read`, `run.interrupt` and `twin.diff`, and its
record moves to `12`, while every operation it will lose still works.

**Independent Test**: tier 1 (quickstart §1): a detached start answers its identity and
no event; `run.read` replays each of the seven histories; `twin.diff` on the goldens; a
`12` record round-trips and an `11` is shown and refused a step.

- [X] T007 [US4] The read and the interrupt by identity (R-04, data-model §1, §3; FR-010): `provision.Service` (`internal/provision/client.go`) gains `Describe(ctx, workflowID, runID string) (RunState, error)` over `DescribeWorkflowExecution`, `RunState` in `types.go` (one of `running`, `completed`, `failed`, `cancelled`, `terminated`, `timed_out`); an unknown identity a typed error; `Follow` and `Result`/`ResultOfStep` callable for a run the request names; a new `internal/server/run.go` with the handlers `run.read` (`/v1/run/read`: args `workflow_id` ∈ {`fylgja-provision`, `fylgja-step`, `fylgja-destroy`}, `run_id` optional, the latest run when absent; frames `run` with `state`, every `event` so far, the `out` lines under `render`; a running run ends by EOF with no document; an ended run ends with the `document`, operation `run.read`, `subject.run_id`, the run's findings from its result; `run.unknown` after `Describe` alone) and `run.interrupt` (`/v1/run/interrupt`: `CancelWorkflow` as `follow.go`'s first interrupt, then a document with `run.cancel.requested`; `run.ended` on a closed run; `run.unknown`), both in `internal/api/wire.go`'s `Operations` and `handlers.go`'s table; `internal/api/client.go` gains the two calls. Tests: `internal/server/run_test.go` with the harness's fake workflow service serving each of the seven histories under `internal/provision/testdata/*.history.json` (the events and the document of each, running and ended; SC-005), the unknown identity, the interrupt of a running and an ended run; `internal/provision/client_test.go`'s `Describe`.
  - **Note (Run 7, 2026-10-29)**: research §5.2. `provision.Service` gained `Describe` (NotFound and InvalidArgument, `Invalid RunId.`, both `*UnknownRunError`, verified on the dev server), and three the task did not name: `History`, `Follow` without its long poll, since a running read must end at the events so far; `InputOfStep`, the input `StepDocument` is built from; `ResultOfDestroy`, which no method read. `RunState` carries the run's id beside its state, the latest run's when none is named. `internal/server/run.go` serves both operations (`runReadByIdentity`, `runInterruptByIdentity`, since `runRead` is `intent.read`'s); `workflow_id` is required, the transport's `400`; a workflow outside the three, `fylgja-rehearse` among them, is `run.unknown` before any dial; a running read's handler returns `errRunning` and `answer` ends the answer with no document, logged `outcome=running`. `api.RunRef` gains `state`; `api.Client` gains `RunRead` and `RunInterrupt`, and `Answer.Next` reads a running read's end as `io.EOF`. `run_test.go` replays the seven histories through the provision client itself over the SDK's mock client, ended (each document byte-equal to the one the stream makes of the run's result) and cut half-way (events so far, no document); US4 scenario 6's "no `run` frame" is read as R-04 and data-model §1 give it (§5.2). Files beyond the task's: `internal/cli/create_test.go` (the fake's four methods; the command walk's `notYetCommands`, run.read and run.interrupt, which T009 drops), `internal/cli/answer_test.go` (a case for each operation), `internal/server/server_test.go` (the least request and the `400`s), `internal/api/wire_test.go` (`notYetServed` down to `twin.diff`). `api.schema.json`'s `$defs/run` lacks `state` until T012, so no test holds the read's `run` frame to it.

- [X] T008 [US4] `detach` (R-03, data-model §1; FR-009) in `internal/server/create.go`, `provision.go`, `step.go`, `destroy.go` and `streams.go`: the boolean argument in `operationArgs` for the four runs; under it the answer is `start`, `run` (destroy's written for the detached answer alone) and the `document` (status `ok`, the one finding `run.detached`), the run going on; `dry_run` beside it refused `run.flags.conflict` before any guard; a refusal before the start the document as today; `follow.go` untouched for the stream. Tests in `internal/server/create_test.go`, `provision_test.go`, `step_test.go`, `destroy_test.go` (US4 scenarios 1 and 6) and `exit_test.go`'s shape test (every answer but a running `run.read` ends with a document).
  - **Note (Run 8, 2026-10-29)**: research §5.3. `detach` rides on the request's `options` (`call.detachable`), so `runProvision` and `runStep` answer at the run once `startRun` returns, `detached` (`internal/server/run.go`) writing `run.detached` after what the command had found (a create's snapshot, bundle and compile findings by `carried`, a step's warnings); an interrupt that reached the start still follows and cancels. `runProvision` lives in `follow.go`, so its detach branch is there, after the `run` frame; `followRun`, `startRun` and the stream's path are unchanged, and `streams.go` needed nothing, a detached answer's stream closing with its request. `detachConflict` is the first thing the three runs with `dry_run` do. One file beyond the task's: `internal/provision/client.go` gains `StartDestroyDetached` (`destroy`'s `follow`), since `StartDestroy` follows the destroy run to its end; it still waits for what it cancels first, and its test is `TestADetachedDestroyReadsNoResult`; the CLI's `fakeService` gains it. `exit_test.go`'s shape test (`TestADetachedAnswerIsItsStartItsRunAndItsDocument`) runs the four through the handlers over a `detachService` that fails the test if anything follows the run or reads its result, `twin.step`'s handler standing in as `runStep` since its guards need a twin; `destroy_test.go` is new.

- [X] T009 [US4] The core's CLI: `--detach` on `twin create`, `twin provision`, `twin step` and `twin destroy` (`internal/cli/create.go`, `provision.go`, `step.go`, `destroy.go`; the document's `run.detached` line printed, exit 0), and `fylgja run read --workflow <id> [--run <id>] [--json]` and `fylgja run interrupt --workflow <id> [--run <id>]` in a new `internal/cli/run.go` registered in `root.go` (the `out` lines printed as `send.go` prints a stream's; `--json` the document; a running run's read exits 0 with no document); `contracts/cli.md`'s text is T012's. Tests: `internal/cli/run_test.go` and `--detach` cases in `create_test.go`, `step_test.go`, `destroy_test.go` through the harness (quickstart §3's five lines).
  - **Note (Run 8, 2026-10-29)**: research §5.3. `--detach` on the four commands (`detachUsage`); `fylgja run read|interrupt --workflow <id> [--run <id>]` in `internal/cli/run.go`, `newRunCmd` in `AddCommands`; `--workflow` is sent as given, the server refusing an empty one `run.unknown`. `send` reads a running read's `io.EOF` as the command's end, exit 0. `runDestroy` takes `destroyFlags`, so its callers in eight test files moved. `create_test.go`'s command walk drops `notYetCommands` and walks `newRunCmd`; `connect_test.go`'s `executeClient` adds it; the fake's `Describe` answers no run for a run id other than the one it describes, so quickstart §3's fifth line is `run.unknown`.

- [X] T010 [US5] `twin.diff` (R-05, data-model §1; FR-011) in a new `internal/server/diff.go`: args `from` and `to`, each a filed id or a path sent as a file as `twin.compile` takes one (`snapshot.go`'s validate-and-file, `validate.Intrinsic`); each compiled on the goldens' path (`compile.go`'s, `compiler.Compile` with the registry and the probe registry), both bundles filed, the `step` block from `step.Pair` as `twin.step`'s dry run writes it (`internal/step/plan.go`, `contracts/step.schema.json`), `unchanged: true` when the two bundle ids are one; a refused compile answers the compile's findings at step `compile`; nothing deployed or started; the document `twin.diff` with `snapshot_from`, `snapshot_to`, `bundle_from`, `bundle_to`; `internal/api/wire.go`, `handlers.go`, `internal/api/client.go`; the CLI `fylgja twin diff --from <id|file> --to <id|file> [--json]` in a new `internal/cli/diff.go`. Tests: `internal/server/diff_test.go` on `testdata/snapshot/three-node.json` and `three-node-probed.json` (the two hosts `n1-loop-a`, `n1-loop-b` and their links added, no device changed; SC-006), one snapshot twice (`unchanged`), a snapshot the compile refuses (the compile's finding), an id the store lacks; `internal/cli/diff_test.go`; `internal/step/purity_test.go` unchanged.
  - **Note (Run 9, 2026-10-29)**: research §5.4. `internal/server/diff.go` (`runTwinDiff`) resolves both sides by `resolveSnapshot`, then compiles each by `stage.Compile` and files it by `fileCompiled`, a side equal to the other compiled once; the pair is `step.Between` of the two sides named `snapshot <short>…`; the document names `snapshot_from`, `snapshot_to`, `bundle_from`, `bundle_to` as far as it got, and its `step` is the pair, `findings.StepBlock.Pair` (written alone, read back when the block has no `diff`). One finding against the task's line: the goldens' step names `~n1 (bootstrap)`, since the probed golden's `n1.cli` enables `ethernet-1/10` and `-1/11`; the test asserts that, n1 changed by its bootstrap alone and no artifact moved, and US5 scenario 1's "no device changed" is the operator's to reword. Files beyond the task's: `contracts/findings.schema.json` (the four ids; `step` `oneOf` step.schema.json's block and stages.schema.json's `$defs/step`; 020's description line), `internal/findings/render.go` (the four fields, `StepBlock.Pair`, `DiffBlock`, `UnmarshalJSON`) and `finding_test.go` (`TestATwinDiffDocumentCarriesItsSidesAndItsPair`), `internal/server/server.go` (the count in comments), `internal/api/wire_test.go` (`notYetServed` gone, the path), `internal/cli/answer_test.go` (the twin.diff case), `internal/cli/compile.go` (`newTwinDiffCmd` under `twin`). `contracts/api.schema.json`'s `from` and `to`, `api.md` and `cli.md` are T012's. `internal/step/purity_test.go` unchanged.

- [ ] T011 [US2] `twin.json` `12` (R-06, data-model §2; FR-007): `internal/lab/twin.go`'s `TwinVersion = "12"`; `StageRef`, `step.to.stage` and `RehearsalRef` go from `internal/lab/twin.go` and `internal/lab/wire/types.go` (the worker's rehearsal branches that write them are T034's; until then they write nothing); `contracts/twin.schema.json` → `12` (`$id …/twin/v12`, `twin_version` const `"12"`, `stage` and `rehearsal` removed, `step.to` naming a snapshot alone); the step's rule in `internal/server/step.go` reads the twin's filed snapshot (`snapshots/<snapshot.id>.json`) and the target's and compares `envelope.scope` and `envelope.mapping` (`reader`, `model`, `version`), refusing `step.twin.unsteppable` naming both pairs; `stepNoTarget` goes; `stepScopeUnknown`'s rule extends to any record `< 12`: "the twin was created from a record version this build no longer steps (twin.json N); fylgja twin destroy clears it"; `internal/server/show.go` loses the stage line, the kinds stand. Tests: `internal/lab/twin_test.go` (a `12` round-trips against `contracts/twin.schema.json`; an `11` read from `testdata/contracts/016-probes/` is shown with its version), `internal/server/step_test.go` (an `11` refused naming `twin destroy`; a target of another scope and of another mapping refused from the envelopes; SC-004), `internal/cli/show_test.go` (no stage line; US2 scenarios 7–8).
  - **Note (Run 10, 2026-10-29, unfinished)**: research §5.6. Done: `twin.json` `12` in code and contract; the step's rule from the two envelopes (`twinEnvelope`, `targetUnheld`); `noTargetGiven` in place of `stepNoTarget`; an `11` or earlier refused naming `twin destroy` and shown with `oldRecordNote`; show, verify, stage list, rehearse (its reclaim gone, keyed on the record's rehearsal) and the worker's inputs lose the stage and rehearsal. Tests green in `internal/lab`, `verify`, `provision`, `server`, `stages`, `wire`, and every `internal/cli` test but eleven in `twin_step_test.go` that still expect the stage wording of the step's twin, step and closing lines (`TestStepWarnings`/skipped, `TestStepRuns`, `TestStepInterrupt`, `TestStepRunReportsTheWait`, `TestStepRunReportsTheLoss`, `TestStepBackToAnEarlierMark`, `TestStepFromTheBranchPointToTheHead`, `TestStepNamesEachSidesSnapshot`/8, `TestStepTargetKeepsScopeAndMapping`, `TestStepToASnapshotDryRun`, `TestStepToASnapshotCloses`): each wants its expected text moved to `twin: snapshot <s> (bundle <b>), branch …`, sides named `snapshot <s>…`, `step.stage.skipped` cases deleted (no record view), and `targetUnheld`'s new message; no production change is owed. `make test` therefore fails in `internal/cli` alone; `make build` and `make lint` pass. `scripts/e2e.sh` moved to `twin_version=="12"` only (tier 1's `TestE2EScriptExpectsTheRecordsVersion`); its cases 7 and 8 still step a stage twin with no target and assert the record's stage, which T031 rewrites.

- [X] T012 [US4] The API's schema and the contracts' gained shapes (data-model §1, §12; contracts/README.md): `contracts/api.schema.json` (`$defs/run` gains `state`; `args` gains `detach`, `from`, `to`, `workflow_id`, `run_id`; the `start` frame's enum still carries `fylgja-rehearse` until T034), `contracts/api.md` (the detached answer, `run.read`'s two endings, `run.interrupt`, `twin.diff`; the table's new rows; the lost rows are T036's), `contracts/cli.md` (`--detach`, `fylgja run read|interrupt`, `twin diff`); `internal/api/wire_test.go` validates each new frame against the schema. Version `1`, unmoved (R-04).
  - **Note (Run 11, 2026-10-29)**: research §5.5. `contracts/api.schema.json`: 020's line in its description; `detach` on the four runs' args (`twin.destroy`'s first property); `$defs/args` gains `run.read` and `run.interrupt` (`workflow_id` required, the transport's `400` as the server has it, any string, a workflow outside the three the server's `run.unknown`; `run_id`) and `twin.diff` (`from`, `to`); `$defs/run` gains `state`, the six of `provision.RunState`; the frame's description names the one answer whose last line is no document; `request.files` names twin.diff's; the `start` enum unmoved. `contracts/api.md`: the table's rows and three new ones, the strict decode's `workflow_id`, the answer's and the frame table's exceptions for a running `run.read`, twin.diff's files, and a section "020: runs by identity and the diff" (the detached answer, `run.read`'s two endings, `run.interrupt`, `twin.diff`). `contracts/cli.md`: the client's commands, the runs' re-attach sentence, and a section of the same name (the commands, the text from the tests, the five identifiers, formats, workflows). `wire_test.go` holds each new request and frame, `state` in each of its six values and refused otherwise. Files beyond the task's: `internal/server/server_test.go` (`TestOperationArgsAreTheContracts`: each operation's args in the schema are `operationArgs`, by name and kind), `internal/cli/answer_test.go` (a detached create and an ended `run.read` through the harness's server, whose every frame is held to the schema, so the read's `run` frame with its `state` now is). The frozen 016 `api.schema.json` of data-model §1 is not made here: 020's change so far is additive, and it is T036's, with the lost operations.

**Checkpoint**: the core serves its new operations beside its old ones; tier 1 green.

---

## Phase 4: User Story 7 — the orchestrator's toolchain (Priority: P3)

**Goal**: `orchestrator/` exists with its venv, test runner and linter in `make` and CI,
so every later run's pure gate covers the Python.

**Independent Test**: `make test` runs `pytest` beside `go test` and `make lint` runs
`ruff`; CI's unit and lint jobs name Python 3.14.

- [ ] T013 [US7] The orchestrator's layout (R-02, FR-017, FR-026): `orchestrator/pyproject.toml` (package `fylgja_orchestrator` under `src/`, `requires-python >=3.14`, `prefect==3.9.0`, `infrahub-sdk==1.23.2`, `httpx`, `pydantic`, `pyyaml`; `[project.scripts]` `fylgja-cli` and `fylgja-orchestrator`; `[project.optional-dependencies] dev` with `pytest==9.2.0` and `ruff==0.17.3`; `[tool.pytest.ini_options]` markers `contract` and `testpaths`; `[tool.ruff]` selecting E, F, W, B, SIM, line length as the checks use); `src/fylgja_orchestrator/__init__.py` and empty packages `adapters/infrahub/`, `documents/`, `flows/`; `tests/unit/`, `tests/contract/` (a `conftest.py` that skips `contract` without `INFRAHUB_ADDRESS`), `tests/golden/` (T003's), `tests/data/`; `orchestrator/.venv` made by a new `make orchestrator-venv` (`python3 -m venv orchestrator/.venv && orchestrator/.venv/bin/pip install -e 'orchestrator[dev]'`) with a `.gitignore` of `*` written inside it as the root `.venv` has; `Makefile`: `test` runs `go test $(PKGS)` then `orchestrator/.venv/bin/pytest -q orchestrator -m 'not contract'`, `lint` adds `orchestrator/.venv/bin/ruff check orchestrator infrahub/checks`, `test-contract` adds `orchestrator/.venv/bin/pytest -q orchestrator -m contract` after the Go packages (its own `rc`), new `prefect-server` and `orchestrator-serve` (each with `PREFECT_HOME`, `PREFECT_API_URL` and the auth string from the environment, `local/orchestrator/prefect` the home); `scripts/converge-loop.sh`'s `seed_worktree` lists `orchestrator/.venv` beside `.venv`, its test in `scripts/tests/test_converge_loop.py` following; `docs/development.md`'s make-targets section is T037's. Verify `make test` wall time against the budget and record it in research §5.

- [ ] T014 [US7] CI (FR-026, SC-009) in `.github/workflows/ci.yml`: the `unit` and `lint` jobs gain `actions/setup-python@v6` with `python-version: '3.14'` and `make orchestrator-venv` before `make test` and `make lint`; the `contract` job the same before `make test-contract`; the Go steps unchanged; `release.yml`'s `make test` the same. The `go generate` step is T035's.

**Checkpoint**: the tree is green with the Python gates in it.

---

## Phase 5: User Story 3 — the adapter's port (Priority: P1)

**Goal**: `python -m fylgja_orchestrator.adapters.infrahub read|stages|schema-check`
writes the snapshot the Go reader writes, byte for byte, with every rule and refusal
carried over.

**Independent Test**: tier 2 (quickstart §4, §7): the fixture's read files `0940db93…`;
each ported `test_read_*`, `test_stages_*`, `test_stage_*` green; `test_adapter_matches_go_reader`
byte-equal on the fixture and a throwaway branch.

- [ ] T015 [US3] `orchestrator/src/fylgja_orchestrator/adapters/infrahub/snapshot.py` (data-model §4, R-07; research §1.6's last bullet): `normalize(ctm)` (the sorts and defaults of `internal/ctm/forms.go`'s `Normalize`), `hashed_bytes(snapshot)` (the Go structs' key order from `internal/snapshot/snapshot.go` and `json.go` and `internal/ctm/json.go`; `json.dumps(…, indent=2, ensure_ascii=False)` with `<`, `>`, `&`, U+2028 and U+2029 escaped as Go's encoder does, plus `\n`; `observed_at` left out), `snapshot_id()` the SHA-256 hex, `write(path, snapshot)` the full document as `Marshal` writes it (`snapshot_version "2"`, `snapshot_id`, `observed_at`, `ctm`, `probes`), `read(path)`. Tests: `tests/unit/test_snapshot.py` against `testdata/snapshot/*.json`'s four ids and a Go-written copy of each (the files copied into `orchestrator/tests/data/snapshot/`, byte-equal after a Python round trip); `tests/contract/test_snapshot_id.py` (`contract`): the fixture's live read is T017's, so this test reads `local/snapshots/0940db93….json` if present else skips with why.

- [ ] T016 [US3] The client, the schema check, the packages and the intrinsic validation (data-model §5; FR-012, FR-013): `client.py` (`infrahub-sdk` 1.23.2's `InfrahubClient` from `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN`, the branch in the path, `at` only when given with at most six fractional digits, `GET /api/schema?branch=` first, `X-INFRAHUB-KEY`; the start-up line `fylgja-infrahub: reading <address> as <reader>@<model version>, scope <scope>`, never the token), `schema.py` (conformance of a branch's schema against `mapping.py`'s kind table ported from `internal/intent/mapping.go` and `schemainfo.go`, kind by kind and field by field as `conformance.go` does; the `schema.*` rules with 017's wording), `packages.py` (`platform.matches` read from `psp/*.yaml` at the repository root found from the installed package's path, `FYLGJA_PSP_DIR` as the override and `FYLGJA_PSP_SHIPPED` when installed elsewhere; `platform.unmatched` naming the pair and every package's pairs; research §4's package-data question answered in research §5), `validate.py` (`internal/validate/rules.go`'s `Intrinsic` rules with their ids). Tests: `tests/unit/test_schema.py` (a schema document lacking a kind, a field, a wrong type, from recorded `GET /api/schema` answers under `tests/data/schema/`), `test_packages.py` (both shipped packages' pairs, an unmatched platform, the override), `test_validate.py` (each intrinsic rule on `tests/data/ctm/` cases copied from `internal/validate`'s testdata).

- [ ] T017 [US3] The read (data-model §5; FR-012, FR-014, FR-015; R-21: read `infrahub:infrahub-common`'s GraphQL references and `infrahub:infrahub-managing-transforms`' `rules/queries-union-fragments.md` first, applying them where `CLAUDE.md` does not decide otherwise): `read.py` with the eleven queries carried over from `internal/intent/queries.graphql` as strings sent through `execute_graphql`, the mapping to CTM `2` from `project.go`, `cable.go`, `artifact.go` and `summary.go` (fidelity rows, `scope.*`, `platform.*`, `intent.at.precision`, `artifact.*` and completeness from `completeness.go`, the errors of `errors.go` with their ids), `stamps.py` (D-058 to D-060 from `stamps.go`: the `Edged*` wrapper's `updated_at`, the query-group's account read as creation), `events.py` (D-048 from `events.go`), `probes.py` (the file, else `FylgjaProbe` on the default branch, else none; `probes 1` validated against `contracts/probes.schema.json`; an empty file or JSON whitespace alone declares none, as `probe.Parse` reads `testdata/probes/none.json`); the read ends by `validate.Intrinsic` then `snapshot.write`. Tests: `tests/unit/test_read.py` on recorded GraphQL answers under `tests/data/graphql/` (the three-node mapping to `testdata/ctm/three-node.json`'s CTM, the lossy and mixed fixtures, each `scope.*` and `platform.*` refusal, the stamps, `at`'s precision), `test_probes.py` (`testdata/probes/*.json` copied into `tests/data/probes/`).

- [ ] T018 [US3] The stages (data-model §5; FR-012; D-045 to D-048): `stages.py` with `Ref` (`<branch>/<label>` parsed as `internal/stages/ref.go`), `find` (the proposed change of a branch, `stage.unknown`, `stages.multiple`), `resolve` (to `(branch, at)` as `resolve.go` and `internal/server/resolve.go` do, the branch point, each mark, the head), `order`, `stale` (`stale.go`'s artifact and mark rules, `stage.artifact.stale` with 014's wording), `main_moved`, `twin_moved` (judged under the record's scope, the record T024's; until then a parameter), `list` (the `stages` block as `blocks.go` and `list.go` build it, `stages.schema.json`), the target rule of `target.go` (the next stage of the twin's own proposed change) and `internal/stage/stage.go`'s read-and-take over `read.py`. Tests: `tests/unit/test_stages.py` on recorded answers under `tests/data/graphql/stages/` (each rule of `internal/stages/*_test.go`'s pure cases carried over, named `test_<go test name in snake case>`), the `stages` block against `tests/golden/stages.json` with its ids substituted.

- [ ] T019 [US3] The adapter's commands and the findings document (data-model §5, §6, §11; R-07; FR-020's document): `documents/findings.py` (the document, `findings 1`, validated against `contracts/findings.schema.json`; its text form as `internal/findings/render.go` renders one, line for line, read beside `internal/server/console.go`'s `out` lines), `documents/rules.py` (every rule the adapter and the orchestrator make, with id, severity, exit, step and wording as data-model §11 lists them, the new five among them; a test holds each id to `findings.schema.json`'s pattern), `documents/stages.py` (the `stages` block's text, held to `tests/golden/stages.txt` and `stages-with-twin.txt`), `adapters/infrahub/__main__.py` (`read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] --out <file> [--json]`, `stages --branch <b> [--scope]`, `schema-check --branch <b>`; the scope from `FYLGJA_DEFAULT_SCOPE` when none, `scope.unset` as today; each exits by its document's status; `--json` the document). Tests: `tests/unit/test_findings.py` (a document of each operation rendered as `internal/findings`' tests render it, from JSON cases under `tests/data/findings/` written by hand from the Go tests), `test_cli_adapter.py` (each command's exit and output on recorded answers).

- [ ] T020 [US3] Tier 2, the reader's ported tests (R-15, FR-028), under `orchestrator/tests/contract/` with the marker `contract`, seeding through `go run -tags fixture ./cmd/fylgja-fixture` as a subprocess on throwaway `fylgja-test-py-<pid>` branches, deleted however the test ends, `cmd/fylgja-fixture/main.go` gaining a flag wherever a Go test's seeding has none (each new flag named in this task's note): `test_read_fixture.py` (`internal/intent/read_contract_test.go`'s assertions: the fixture reads to `0940db93…` and the CTM equals `testdata/ctm/three-node.json` but for the envelope; SC-002), `test_read_conformance.py` (`conformance_contract_test.go`), `test_read_defects.py` (`defects_contract_test.go`), `test_read_probes.py` (`internal/server/probes_contract_test.go`'s `TestProbesFromTheKind` and `internal/cli/probes_contract_test.go`'s `TestIntentReadFilesASnapshot2`: `FylgjaProbe` written on `main` and deleted after, as `testsupport.WriteProbes`/`DeleteProbes` do, through a fixture-tool flag), `test_schema_check.py` (`internal/cli/schema_contract_test.go`'s three: both fixtures pass, a missing branch, no object query issued). Each run alone (`orchestrator/.venv/bin/pytest -q orchestrator -m contract -k <name>`) with no twin up; wall times in research §5.

- [ ] T021 [US3] Tier 2, the stages' ported tests and the compare (R-15, FR-016, FR-028; SC-002): `test_stages.py` (`internal/stages/stages_contract_test.go`'s assertions: a proposed change with marks, the branch point, the head, a stale mark, `main` moved, the list's rows and warnings), `test_stage_take.py` (`internal/stage/artifact_contract_test.go`, `mixed_contract_test.go`, `reproducibility_contract_test.go`: a stage read and taken to a snapshot, the mixed fixture, a pinned read reproducing its snapshot id), `test_snapshot_of_a_stage.py` (`internal/server/snapshot_contract_test.go`'s `TestStageTakenTwiceHasOneSnapshot` and `TestStepTargetFromASnapshot`'s read half); and `test_adapter_matches_go_reader.py`: for `fylgja-fixture`, a throwaway branch with three stages and a probe file, and a pinned `at`, `bin/fylgja intent read … --out go.json` through the host's server and the adapter's `read … --out py.json` with the same arguments, `cmp` byte for byte after each file's `observed_at` lines are equalised, and the `stages` document of each equal as JSON; the adapter's read time beside the Go reader's recorded in research §5. Removed with the Go reader (T035). Each run alone, no twin up.

**Checkpoint**: the adapter reproduces the Go reader on every tier-2 case the Go reader
has, and its snapshot is byte-equal.

---

## Phase 6: User Stories 1, 3, 5 and 6 — the documents, the flows, the record and `fylgja-cli` (Priority: P1, P1, P2, P2)

**Goal**: the orchestrator renders the three documents to the goldens, drives the core
through the API alone, keeps its record, and `fylgja-cli` runs every command the core
loses.

**Independent Test**: tier 1 (the renderers against T003's goldens, the record's rules,
the core client against a stub); tier 2 (quickstart §7's four flow tests).

- [ ] T022 [US1] The documents (data-model §6, R-13, FR-023, SC-007) in `orchestrator/src/fylgja_orchestrator/documents/`: `plan.py` (the `plan` block as `internal/stages/plan.go` builds it from stage snapshots, bundles and `twin.diff`'s step blocks; its text), `rehearsal.py` (the `rehearsal` block and the verdict rules of `internal/rehearsal/verdict.go`'s `Classify`, `NewFindings`, `Stop`, `Build`, `rehearsal.steps.none` as 015 defined it; the text of `report.go`; the markdown of `markdown.go` with `CommentMax` 4,092, the table's `loss` column and caveat, the drawing, and `Reproduce` writing `fylgja-cli twin create --stage … --scope …`, `fylgja-cli twin step --stage … --allow-restart`, `fylgja-cli twin verify`, `fylgja-cli twin destroy`), `deadline.py` (`Deadline`, `Fits`, `Ceiling` 3,600 and `rehearsal.deadline.unfit` from `deadline.go`, over the node plans' budgets read from each compiled bundle's files; research §4's "which file" answered in research §5), each block validated against `contracts/rehearsal.schema.json` and `stages.schema.json`. Tests: `tests/unit/test_plan.py`, `test_rehearsal.py`, `test_deadline.py`: the goldens `plan.json`/`.txt`, `rehearsal.json`/`.txt`/`.md` rendered byte for byte but for `fylgja-cli` in the reproduce lines, the ids substituted from `tests/golden/README.md`; each verdict case of `verdict_test.go` and each markdown case of `markdown_test.go` carried over by name.

- [ ] T023 [P] [US4] The core's client, `orchestrator/src/fylgja_orchestrator/core.py` (data-model §7, R-08; FR-017, FR-022): `FYLGJA_API_ADDRESS` (default `127.0.0.1:7650`) and `FYLGJA_API_TOKEN`, the bearer header, `Fylgja-Api-Versions`; `start(operation, args, files)` sending `detach: true` and returning the identity from the `run` frame, `read(workflow_id, run_id, render=True)` polled every 2 s to the document, `interrupt`, `show`, `compile`, `diff`, `verify`, `destroy`, `dry_run`; the frames parsed as `internal/api/client.go` parses them, the `out` lines surfaced for printing; `api.unreachable` (exit 2) and `api.token.refused` as `internal/cli/failures.go` words them; the stream never opened; the token in no log line. Tests: `tests/unit/test_core.py` against a stub HTTP server answering recorded frame sequences under `tests/data/frames/` (a detached create then its read to completion, a refusal document, a running read's EOF, `401`, a refused connection).

- [ ] T024 [P] [US6] The record and the store, `orchestrator/src/fylgja_orchestrator/record.py` (data-model §8, R-09; FR-021): `FYLGJA_ORCHESTRATOR_ROOT` (default `local/orchestrator`); `snapshots/<id>.json` filed once by `os.link` from a temporary file, a second take writing nothing; `twin.json` `{"record_version": "1", "stage": {"branch", "label", "at"}, "proposed_change": {"id", "branch"}, "snapshot_id", "flow_run_id", "flow", "written_at"}` written whole by the create, step and rehearse flows; `trusted(record, show)` true while `twin.show`'s `show.record.snapshot_id` (`contracts/show.schema.json`) equals `snapshot_id`; distrusted, `record.twin.stale` (info) and no twin row, `twin step` without `--stage` refused `step.target.required` (error, exit 1); `reclaimable(record, flow_run)`: the record's `flow` is `twin-rehearse` and `GET /api/flow_runs/{flow_run_id}` is terminal (`FAILED`, `CRASHED`, `CANCELLED`) or `404`, and `twin.show` names the record's snapshot; anything else the host held. Tests: `tests/unit/test_record.py` (US6 scenarios 1, 2, 4 and 5 over a temporary root and stubbed `show` and run-state answers).

- [ ] T025 [US3] The five flows (data-model §7, R-08; FR-018) in `orchestrator/src/fylgja_orchestrator/flows/`: `intent_read.py` (`@flow(name="intent-read")`: the adapter's read, the file at `--out`, the summary line), `schema_check.py` (`schema-check`, passed through), `twin_create.py` (`twin-create`: the read, the snapshot filed under the record's `snapshots/`, `twin.create` detached then polled, the `out` lines printed as they arrive, the record written; `dry_run` passed through with the file, printing the dry run's lines and writing no record), `twin_step.py` (`twin-step`: the target the next stage of the record's own proposed change when `--stage` is absent, `step.target.required` when distrusted; `stage.twin.moved` judged from the record; `twin.step` with `allow_restart`, `wait`, `dry_run`; the record moved), `stage_plan.py` (`stage-plan`: every stage read through the adapter, each compiled by `twin.compile`, each pair's step by `twin.diff`, the `plan` block); each ends by writing its findings document as the run's artifact `fylgja-findings` (key `fylgja-<flow>-<run id>`, `data` the JSON) and returning it; each named flow has a deployment `main` (T027). Tests: `tests/unit/test_flows.py` with the adapter and `core.py` stubbed (each flow's document on the recorded cases, `dry_run` writing no record, the default target, the moved rule), run under `prefect_test_harness` or with the flow functions called plain, whichever keeps `make test` in budget (recorded in research §5).

- [ ] T026 [US1] The rehearse flow, `flows/twin_rehearse.py` (data-model §7, R-09 to R-11; FR-019): the plan (T025's `stage_plan`), the reclaim (T024's rule; `rehearsal.twin.reclaimed` naming the run and what was removed; else `host.twin.present`), the baseline rule re-made over the core's operations (015 R-03: the branch point's snapshot created with `twin.create`), each later stage stepped with `twin.step` and its wait and verified, stopping at the first that fails, every run detached and polled, the verdicts and the report (T022), the thread and comment posted on the proposed change through the SDK on `main` (the code of `infrahub/checks/fylgja_api.py`'s `post_comment` moved here, the 4,092-byte cut by the renderer; `rehearsal.report.unposted` (warning) when the post fails, the status kept), the document as the run's artifact; `timeout_seconds` the deadline (T022's `deadline.py`); `finally`: `twin.destroy` and the report's cut (`rehearsal.deadline.cut`) on a timeout or a cancellation (research §1.5; §4's grace question measured and recorded in research §5, the setting changed if the destroy does not finish). Tests: `tests/unit/test_rehearse.py` with the adapter and `core.py` stubbed: the composition of 015's `TestRehearse*` pure cases by name, the stop at the first failed stage, the reclaim's four cases, the cut, the unposted report.

- [ ] T027 [US3] `fylgja-cli` and the runner (R-02, R-08; FR-020): `orchestrator/src/fylgja_orchestrator/cli.py` (`argparse`, noun-verb: `intent read --branch <b> [--at] [--stage] [--scope] [--probes] --out <f>`, `stage list [--branch] [--scope]`, `stage plan --branch <b> [--scope] [--probes]`, `twin create --branch <b>|--stage <b>/<l> [--scope] [--probes] [--dry-run]`, `twin step [--stage] [--probes] [--allow-restart] [--wait <d>] [--dry-run]`, `twin rehearse --branch <b> [--scope] [--probes] [--markdown]`, `schema check --branch <b>`, `--json` everywhere; each runs its flow function in-process, recorded on the platform when `PREFECT_API_URL` is set, prints the `out` lines as they arrive, then the document's text or JSON, exiting by its status; `platform.unreachable` (error, exit 2) when `PREFECT_API_URL` is set and the server does not answer; the usage lines as `internal/cli/root.go`'s), `serve.py` (`fylgja-orchestrator serve`: `serve(<each flow>.to_deployment(name="main"), …)` for the six, its start-up line naming the platform's address and the six deployments, never the auth string). Tests: `tests/unit/test_cli.py` (each command's flags, exit and output with the flows stubbed; `--json` the document; the unknown command's exit 2).

- [ ] T028 [US1] Tier 2, the flows (R-15, FR-028; quickstart §7), under `orchestrator/tests/contract/`, each starting a core server of its own from `bin/fylgja` with `--listen 127.0.0.1:0`, a token it makes, `FYLGJA_STATE_ROOT` under a temporary directory and **no `INFRAHUB_*`**, against the host's dev server on `:7233`, under `prefect_test_harness` (research §4's ephemeral-server facts, the first start's time, recorded in research §5), seeding through the fixture tool, no twin booted: `test_flows_create_from_fixture.py` (`twin-create --branch fylgja-fixture --dry-run`: the document names bundle `c3872f5c…` and snapshot `0940db93…`; SC-002), `test_stage_plan_of_a_throwaway_change.py` (a proposed change with three stages: the `plan` block's steps equal `bin/fylgja stage plan --branch … --json`'s through the host's server, compared while the Go handler stands (SC-006), the comparison removed at T035), `test_rehearse_refused_on_a_stale_mark.py` (`stage.artifact.stale` before any run; US1 scenario 5), `test_rehearse_composed_by_the_fixture_tool.py` (`internal/server/rehearse_contract_test.go`'s `TestRehearseComposedByTheFixtureTool` carried over: the draft's refusal, the ready change's plan, the host held). Each run alone; wall times in research §5.

**Checkpoint**: the orchestrator is whole; the core still serves what it will lose.

---

## Phase 7: User Story 1 — the checks, the host's scripts and tier 3's script (Priority: P1)

**Goal**: the two checks are the orchestrator's clients, the host's scripts know five
processes, and tier 3 runs through `fylgja-cli`.

**Independent Test**: `ruff` and the checks' unit cases; `shellcheck`; tier 3's script
checked offline against the latest recorded outputs; the live proof is Phase 12's.

- [ ] T029 [P] [US1] The checks' glue (data-model §9, R-12; FR-024; after `infrahub:infrahub-managing-checks`' SKILL.md is read, R-21): `infrahub/checks/fylgja_api.py` becomes the platform's client: `FYLGJA_ORCHESTRATOR_ADDRESS` and `FYLGJA_ORCHESTRATOR_AUTH` (basic auth on `httpx`), `trigger(flow, parameters) -> flow_run_id` (`GET /api/deployments/name/<flow>/main`, `POST …/create_flow_run`, one retry on `503`), `wait(flow_run_id, deadline) -> state` (poll 5 s), `document(flow_run_id)` (`POST /api/artifacts/filter`, `data` parsed), `cancel(flow_run_id)` (`set_state CANCELLING`, `force`); `post_comment` and the `/v1/` paths removed; the R-15 retry while held and the margins unchanged; `fylgja_step.py` triggers `stage-plan` and concludes as today; `fylgja_twin.py` skips a draft, triggers `twin-rehearse`, waits, concludes from `status` alone, posts nothing, cancels at its deadline; `timeout` 4260 unmoved; `.infrahub.yml`'s comment on the checks alone; `contracts/checks.md` written from `specs/015-proposed-change-rehearsal/contracts/checks.md` with the new reach; `internal/checks/checks_contract_test.go`'s precheck reads `FYLGJA_ORCHESTRATOR_ADDRESS` from inside a task worker (`GET /api/health` and an authenticated deployment read) and skips, saying why, where none answers; `orchestrator/tests/unit/test_checks_glue.py` imports `infrahub/checks/fylgja_api.py` by path and tests `trigger`'s retry, `wait`'s states and `document`'s parse against a stub. The `__pycache__` under `infrahub/checks/` stays untracked.

- [ ] T030 [P] [US7] The host's scripts (data-model §10, R-17, R-18; FR-005, FR-026): `scripts/infrahub/docker-compose.override.yml`'s `task-worker.environment` becomes `FYLGJA_ORCHESTRATOR_ADDRESS: host.docker.internal:4200` and `FYLGJA_ORCHESTRATOR_AUTH: ${FYLGJA_ORCHESTRATOR_AUTH}`, its comment rewritten; `.env.example` gains `FYLGJA_ORCHESTRATOR_AUTH`, `FYLGJA_ORCHESTRATOR_ROOT`, `PREFECT_API_URL`, `PREFECT_API_AUTH_STRING` with who reads each, and its `INFRAHUB_*` and `FYLGJA_DEFAULT_SCOPE` comments say the orchestrator reads them, never the server; `scripts/bring-up.sh`: `PARTS_ALL` gains `orchestrator` (the venv by `make orchestrator-venv`, `FYLGJA_ORCHESTRATOR_AUTH` made and written into a new `local/.env`, kept byte for byte when present with a note when the name is absent as `scope_named` does, `prefect server start --host <bridge> --port 4200 --no-ui` with `PREFECT_HOME=local/orchestrator/prefect` detached to `local/prefect.log`, `fylgja-orchestrator serve` detached to `local/orchestrator.log`, each verified as the three processes are), `part_fylgja`'s `serve` loses `--listen "$BRIDGE_ADDR:7650"` and its environment the `INFRAHUB_*` and scope lines, `listens_on`'s bridge check moves to the platform, the summary names five processes; `shellcheck scripts/bring-up.sh` clean. Nothing run on the host here (T040).

- [ ] T031 [US1] Tier 3's script (R-16, FR-029): `scripts/e2e.sh` runs `fylgja-cli` (`orchestrator/.venv/bin/fylgja-cli`) for every command naming a branch or a stage in cases 1 to 8, case 3's dry run among them, with `FYLGJA_ORCHESTRATOR_ROOT=$OUT/orchestrator`, `PREFECT_HOME=$OUT/prefect` and no `PREFECT_API_URL` (the ephemeral server), and `bin/fylgja` for the rest; its own core server started with no `INFRAHUB_*`; each client call's environment gains `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE` for `fylgja-cli` alone; case 9's precheck a `GET /api/health` and an authenticated `/api/deployments/name/twin-rehearse/main` from inside a task worker and the core's `7650` unreachable from there; `rehearsal_run` reads the flow run by the identity the report names (`GET /api/flow_runs/{id}` with the auth string from `local/.env`) and the core's Temporal runs; the reproduce block's assertion names `fylgja-cli twin create --stage …`; the credential greps add `local/prefect.log`, `local/orchestrator.log`, `$OUT/prefect/` and the platform's auth string; the core's server log asserted to name no Infrahub request; `shellcheck scripts/e2e.sh` clean; checked offline against the latest `local/e2e-*.outputs` (the new assertions dry-run against them where their shape allows; the rest noted for T043).

**Checkpoint**: the checks and the scripts are the orchestrator's; nothing live has run.

---

## Phase 8: User Stories 2 and 7 — the removal (Priority: P1, P3)

**Goal**: the five operations, their arguments, the rehearse workflow, the reader packages
and `internal/rehearsal` leave the core, held by the boundary test.

**Independent Test**: tier 1 (quickstart §1): the five paths `404`, the five arguments
`400`, the five commands unknown; three workflows; `TestTheCoreLinksNoReader`; `make test`
in budget.

- [ ] T032 [US2] The server's removal (data-model §1; FR-002, FR-004, FR-006; R-18, R-19): `internal/server/rehearse.go`, `stages.go`, `schema.go`, `scope.go`, `read.go`, `resolve.go` and the kind's half of `probes.go` go with their tests (`rehearse_test.go`, `rehearse_contract_test.go`, `schema_test.go`, `scope_test.go`, `read_test.go`, `probes_test.go`'s kind cases, `snapshot_contract_test.go`'s stage cases, `probes_contract_test.go`); `handlers.go`'s table and `internal/api/wire.go`'s `Operations` lose `twin.rehearse`, `stage.list`, `stage.plan`, `intent.read`, `schema.check`; `operationArgs` loses `branch`, `at`, `stage`, `scope`, `probes`; `snapshot.flags.conflict` goes; `options.go` and `server.go` lose the Infrahub client and the default scope; `cmd/fylgja/serve.go` reads no `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` or `FYLGJA_DEFAULT_SCOPE`, its report says `the workflow service (<addr>), Docker, containerlab and the nodes are dialled when a request needs them` and names no default scope, the "not a loopback address" warning stays; `contracts/api.schema.json`'s `start` enum loses `fylgja-rehearse`. Tests: a new `internal/server/gone_test.go` (each lost path `404` without `Fylgja-Api-Versions`, body `API version 1 has no operation at this path; nothing was read or done`; each lost argument on `twin.create` and `twin.step` `400` "takes no argument"; SC-003), `cmd/fylgja/serve_test.go` (starts with the three variables unset, the report's lines).

- [ ] T033 [US2] The CLI's removal (FR-003): `internal/cli/rehearse.go`, `stages.go`, `schema.go`, `read.go` go; `create.go` and `step.go` lose `--branch`, `--at`, `--stage`, `--scope`, `--probes`; `root.go` loses the `stage`, `intent` and `schema` nouns; their tests go (`intent_test.go`, `schema_test.go`, `schema_contract_test.go`, `stage_test.go`, `stage_create_test.go`, `stage_list_test.go`, `stage_plan_test.go`, `stage_conformance_test.go`, `stage_parity_test.go`, `stages_test.go`, `twin_rehearse_test.go`, `twin_rehearse_host_test.go`, `infrahub_test.go`, `probes_contract_test.go`, `create_snapshot_test.go`'s stage cases, `credential_test.go`'s Infrahub cases); the harness in `harness_test.go` loses its placeholder Infrahub; `gone_test.go` gains the five commands and five flags each ending `unknown command`/`unknown flag`, exit 2, with no request sent (US2 scenario 3); `main_test.go`'s `--version` and `--help` with no server.

- [ ] T034 [US2] The worker's removal (data-model §3; FR-008): `internal/provision/workflow_rehearse.go` and `workflow_rehearse_test.go` go; `client.go` loses `StartRehearse`, `ResultOfRehearse`, `StartReclaim`, `rehearseStartOptions`, the rehearsal branches of `InFlight`, `historyStep` and `StartDestroy`, and `Follow`'s child-following branch (research §1.6, the 015 defect gone with the parent); `types.go` loses `RehearseInput`, `RehearseResult` and `Child`; `options.go` loses `WorkflowRehearse`; `internal/lab/wire/types.go` loses `RehearsalRef`; `worker.go` registers `Provision`, `Destroy`, `Step`; `worker_test.go`'s `TestWorkerRegistersEveryScheduledActivity` pins three workflows and seventeen activities; `determinism_test.go` drops `workflow_rehearse.go`; `workflow_replay_test.go`'s seven histories replay unchanged (SC-004); `cmd/fylgja/worker.go`'s report unchanged (US2 scenario 6).

- [ ] T035 [US7] The packages' removal and the boundary (FR-001, FR-016, R-15; data-model §11; SC-003): `internal/intent/`, `internal/stages/`, `internal/stage/`, `internal/rehearsal/` deleted whole; `schema/infrahub.graphql`, `make sdl`, `make generate` and CI's `go generate … && git diff --exit-code` step go with genqlient (`go mod tidy`; `go.sum` follows); `internal/testsupport` keeps what `cmd/fylgja-fixture` and the Go tier 2 (`internal/checks`, `internal/server`'s remaining contract tests) use and loses the rest; `internal/findings/finding.go` retires `scope.invalid`, `scope.unset`, `scope.empty`, every `stage.*`, `stages.*`, `rehearsal.*`, `schema.*`, `intent.*`, `probe.kind.absent`, `probes.*`, `snapshot.flags.conflict`, `step.target.unknown`, `step.target.current`, `step.stage.skipped`, and `render.go` their renderers (`rehearsal_test.go`, `stages_test.go` go); `contracts/findings.schema.json`'s enum loses the five operations and the retired rules; a `TestTheOrchestratorsRulesAreRetired` in `finding_test.go` holds each retired id absent from the core and present in `orchestrator/src/fylgja_orchestrator/documents/rules.py` (read as a file); a `TestTheCoreLinksNoReader` beside `TestClientReachesTheCoreThroughTheAPIAlone` in `internal/compiler/purity_test.go`: no package `cmd/fylgja` links imports `github.com/Khan/genqlient`, `infrahub` in any path, or `internal/intent`, `internal/stages`, `internal/stage`, `internal/rehearsal`, and none of the four directories exists; `orchestrator/tests/contract/test_adapter_matches_go_reader.py` and T028's Go comparison go (R-15), their last green runs cited in this task's note from research §5; `make test`'s wall time read again.

- [ ] T036 [US7] The contracts' prose (data-model §12, R-13; FR-030; contracts/README.md): `contracts/api.md` (the five operations lost with the `404` wording, the table as contracts/README.md draws it, the `run` frame's `state`, the detached answer's three frames, `run.read`'s one answer with no document), `contracts/cli.md` (the lost commands and flags, `fylgja serve` reading no `INFRAHUB_*` and no scope, its report's dial line), a new `contracts/orchestrator.md` (`fylgja-cli`'s commands and refusals, the three documents with `rehearsal.schema.json` and `stages.schema.json` as its, the adapter's commands and environment, the six deployments and the artifact, the platform's auth, the record), `contracts/checks.md` (T029) linked from it; `specs/014-proposed-change-stages/contracts/stage-commands.md` and `specs/015-proposed-change-rehearsal/contracts/rehearse-command.md` each gain one line at the top naming `contracts/orchestrator.md` as current; `make linkcheck` clean.

**Checkpoint**: the core is the core; tier 1 green inside its budget, three workflows,
no reader.

---

## Phase 9: User Story 7 — the documents (Priority: P3)

**Goal**: the architecture, the C4 model, the development notes, the glossary, the brief,
the README and the threat model say what is now true.

**Independent Test**: SC-011's grep over the tracked documents finds the rehearsal as a
workflow, the server on the bridge and the reader in Go nowhere but the decision log's
superseded entries, the archive and the release notes; `make linkcheck` clean.

- [ ] T037 [P] [US7] `docs/architecture.md` (FR-031: §1's claims and §2's pipeline on two deployables, §4.1 the reader as the orchestrator's adapter in Python, §4.4 three workflows and the long-operation shape, §4.6 the two CLIs and the operations lost and gained, a new §4.7 "The orchestrator" (the platform, the six flows, the record and the store, the checks' reach, the deadline, the report) with 016's §4.7 renumbered §4.8, §5's stack naming Prefect 3.9.0 and Python 3.14 beside Go, §6's limitations), each superseded position of D-065 and D-066 found by grep and reworded; `docs/c4/workspace.dsl` redrawn (the orchestrator container with its platform, the adapter, the checks reaching the platform on the bridge, the core's server on loopback; the component views) and `make diagrams` run, its `.puml` and `.svg` committed; `docs/development.md` (Local environment's five processes and the orchestrator's venv, Repository layout with `orchestrator/`, Build and make targets, Test architecture's tiers with the Python tests, the import graph, Spec Kit workflow's lane seed).

- [ ] T038 [P] [US7] `docs/glossary.md` (Core, Orchestrator, Adapter, Tool, Flow (orchestrator) and Runner added, Flow told apart from 016's and Runner from the core's worker and Infrahub's task workers; Client, Server, Rehearsal, Stage and Check (Infrahub) reworded), `docs/brief.md` (two deployables), `README.md` (the walk-throughs through `fylgja-cli` for a branch or a stage and `fylgja` for a snapshot, the five processes, the install of the orchestrator), `SECURITY.md` (the threat model: the core's token on loopback alone, the platform's auth string on the bridge, the checks holding the orchestrator's credential and never the core's, the adapter holding Infrahub's token and never the API's; FR-005); the credential names in each checked against `.env.example`.

**Checkpoint**: every tracked document true but the records (Phase 13).

---

## Phase 10: The operator's import

**Purpose**: the checks reach Infrahub by the only road there is (`CLAUDE.md`,
Environment), at the latest point tier 2's `TestChecksInsideInfrahub` and tier 3's case 9
allow.

- [ ] T039 [operator] Push the checks and import them, since the import waits on the pushed tree: the registration `fylgja` tracks `origin`'s `main`, which only the operator pushes. Once T029's `fylgja_api.py`, `fylgja_step.py`, `fylgja_twin.py` and `.infrahub.yml` are in the tree, put their change on `main` (the checks' commit alone cherry-picked, as 016's T041 did, or the branch merged), push `origin`'s `main`, run `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on `main` for the registration `fylgja`, and read both task workers' `commits/` for the new commit about 15 s after the import's flow; record the commit and the time in this task's note. Before T040, since from this import every proposed change's checks need the override's variables, which T040's `up -d` gives the task workers.

---

## Phase 11: User Stories 1–6, live — the host and the hand scenarios (Priority: P1)

**Goal**: five processes from this tree on the development host, Infrahub's task workers
reaching the platform on the bridge and the core not at all, research §4's facts
verified, and quickstart §2–§6 run by hand.

**Independent Test**: quickstart §2–§6's expected outcomes, each recorded in its task's note.

- [ ] T040 [live] [US7] The host (quickstart §0, §6; research §4; SC-010; the brief's "not the operator's"): `free -m` read, Infrahub's containers restarted if it reads well below `CLAUDE.md`'s figure; `make build` static from a commit; `FYLGJA_ORCHESTRATOR_AUTH`, `FYLGJA_ORCHESTRATOR_ROOT`, `PREFECT_API_URL` (`http://<bridge>:4200/api`) and `PREFECT_API_AUTH_STRING` appended to `local/.env` by name (never re-made; `scripts/bring-up.sh --part orchestrator` if it needs no sudo, else its steps by hand), the venv present; the Prefect server and the runner started detached as T030's part starts them and verified (`/api/health` 200, the six deployments by an authenticated read, no auth string in either log); the worker restarted from this tree and verified as `CLAUDE.md` says; the core's server restarted with **no `INFRAHUB_*` or `FYLGJA_DEFAULT_SCOPE`** in its environment and no bridge `--listen`, its report read (quickstart §2's lines); then, with no twin up and no tier running, the task workers recreated with the changed override (`docker compose -p fylgja-infrahub --env-file local/.env -f local/infrahub/docker-compose.yml -f local/infrahub/docker-compose.override.yml up -d` from the repository root) and from inside each the deployment read `200` and `…7650/v1/twin/show` refused to connect (quickstart §6's two commands); research §4's measurements still owed taken here (the runner's poll interval, the flow's overhead between `create_flow_run` and the first core request, the destroy under cancellation's grace). Every fact and figure in research §5.

- [ ] T041 [live] [US1] The hand scenarios, on throwaway `fylgja-test-qs-<pid>` branches, never `fylgja-fixture`, no tier at the same time: **quickstart §2** (US2: the core with no Infrahub, a create from `0940db93…` by id building `c3872f5c…`, `twin show` naming no stage, `--branch` an unknown flag, `/v1/stage/list` `404`), **§3** (US4: the detached create, the read, the interrupt, the read once ended, the unknown run), **§4** (US3 scenario 1, SC-002: the adapter's read of the fixture to `0940db93…`, `stages` on the fixture `stage.unknown`, `schema-check` exit 0; the `cmp` against the Go reader no longer possible, the last green compare cited from research §5), **§5** (US3, US5, US6: the plan with four stages and three steps from `twin.diff`, the create from a stage with the record written, the list's twin row, the default step, the record left stale by `fylgja twin step --snapshot`, `record.twin.stale`, `step.target.required`, the dry run refused while held then its lines after the destroy; `/api/flow_runs/filter` listing each run; `grep -c Bearer local/orchestrator.log` 0), **§6** (US1: `fylgja-cli twin rehearse --branch … --markdown` on the ready change printing the report and posting one thread whose reproduce lines name `fylgja-cli`, `local/server.log` growing by the core's operations alone, then `-run-checks user` rehearsing it twice through the bridge as case 9 does, the thread's table carrying `loss`). Each branch deleted after; the counts of T001 read again; every figure in research §5; a defect found is fixed in its package with a tier-1 test that pins it.

**Checkpoint**: the host runs this tree; the one criterion proven by hand.

---

## Phase 12: Live — tier 2 and tier 3

**Goal**: the contract tier whole and the end-to-end tier whole (SC-001, SC-002, SC-008).

**Independent Test**: quickstart §7 and §8's expected outcomes.

- [ ] T042 [live] [US1] `make test-contract` whole (quickstart §7): the Go packages, `internal/checks` alone through the platform on the bridge (`TestChecksInsideInfrahub` green, the checks imported by T039), then `pytest -m contract`, with the Prefect server, the runner and the core's server on loopback from this tree (T040), no twin up and none booted while it runs; the wall time whole and of each half, the Go tier's without `internal/stages`, recorded in research §5 (R-15); Infrahub left as T001 found it (`CoreProposedChange`, `FylgjaStage`, `FylgjaProbe`, `CoreChangeThread`, `CoreUserValidator` 0; `Branch` `main` and `fylgja-fixture`); a package that lapses under the tier's own load re-run alone and said so.

- [ ] T043 [live] [US1] Tier 3 (quickstart §8), on a quiet host after T042, from a commit whose `vcs.revision` the running binaries carry (restart both core processes if a commit replaced the binary): `free -m` read and Infrahub's containers restarted if low; `make test-e2e` detached with its exit status in `local/converge-e2e.out`, waited on in calls under ten minutes; expected `E2E-OK`, nine cases, cases 1 to 8 through `fylgja-cli`, case 9's two rehearsals through `fylgja-twin`, the thread's table carrying `loss`, the credential greps over the orchestrator's logs and the platform's finding nothing, the core's server log naming no Infrahub request (SC-001, SC-008); the wall time and each case's, with case 9's flow overhead against `fylgja-twin`'s 4260, in research §5; the host left clean (`clab inspect --all` `{}`, no `local/twin`, no `fylgja-test-*` branch); `PLATFORMS=nokia_srlinux` not run unless the whole run fails on an EOS case.

**Checkpoint**: tiers 2 and 3 green.

---

## Phase 13: The records at the close

**Purpose**: every record true, the feature closed (research §4; quickstart §9).

- [ ] T044 [P] `docs/verified-facts.md`, each with the version and the date, from research §1 and §5: a new "Prefect 3.9.0" section (the install on Python 3.14.4, the server's basic auth and its `/api/health`, a deployment triggered, polled, read and cancelled over HTTP, the `503` at start, the artifact's `data` as a JSON string, `finally` and the hooks on a timeout and a cancellation with the grace measured, the ephemeral server and `prefect_test_harness`, the runner's poll interval, the flow's overhead); under Infrahub 1.11.2 a "The embedded Prefect" heading (research §1.1: a separate server on the Compose network, unpublished, the task workers' environment, their Prefect 3.7.5 and `httpx`); "The snapshot id in Python" moved from the NetBox section's aside to its own line beside the adapter's read time; the host's five processes; the tiers' times from T042 and T043.

- [ ] T045 [P] `docs/roadmap.md`: F-027 marked built (its table row, its paragraph with the closing date and the measured effort from this feature's command logs against R-22's 24–36, Release 0.3's item 5 **Built** under D-065, D-066 and Constitution 3.0.0, the next spec moved to item 6, F-025, with its dependency on this feature's adapter contract, the Backlog's built sentence naming F-027 as `020-core-orchestrator-split`); the production shape's "a direction, not a decision" line becomes a record of what was decided here (the brief's Hand-off); 0.3's upgrade list gains the five processes and the checks' new reach.

- [ ] T046 `CLAUDE.md` (quickstart §9): the opening paragraph (two deployables; every command of the core a request to `fylgja serve`, every command naming a branch or a stage `fylgja-cli`'s), Workflow's Infrahub-skills bullet (the adapter's queries), Environment (`local/.env`'s new names and who reads each; the override's two variables; the five processes with the Prefect server's and the runner's detached commands and how each is verified; the server's command with no bridge listener and no `INFRAHUB_*`; the task workers reaching `4200`; the registration's import at T039's commit; the worker's three workflows), Formats (`twin.json` `12`; the API's new operations; the orchestrator's record `1`; the documents the orchestrator owns), Build and test (`make orchestrator-venv`, `make test` with `pytest` and its measured time, `make test-contract`'s three parts and their times, tier 3's time and shape), Milestones unchanged, State rewritten whole with 020's close.

- [ ] T047 The closing gates and greps, on the final tree: `make build` static; `make test` uncached under 65 s (SC-009) or the budget raised with the figure in `CLAUDE.md` and `docs/development.md`; `make lint`; `go vet -tags contract,fixture,e2e ./...`; `make linkcheck`; `git diff --stat main -- testdata/golden testdata/snapshot testdata/ctm schema/dcim infrahub/templates infrahub/queries` empty (FR-033); SC-011's grep (`/usr/bin/grep -rn 'fylgja-rehearse\|bridge.*7650\|internal/intent' docs README.md contracts SECURITY.md CLAUDE.md`) finding only the decision log's superseded entries, the archive and the release notes; the credential greps (`/usr/bin/grep`, never the wrapper) over the tree, `local/server.log`, `local/worker.log`, `local/orchestrator.log`, `local/prefect.log` and `local/orchestrator/prefect/` for the token, the auth string, both logins and the admin token, nothing found; the worker and the server read (`/proc/<pid>/exe`, the binary's `vcs.revision` against `HEAD`'s) and reported, not restarted: this run is pure, so when the records' commits have moved the stamp, the restart from the final build is a live session's or the operator's, as 016's T049 ended; research §5's measured effort against R-22. Report each in this task's note.

- [ ] T048 [operator] The review, the merge and the push, because they are the operator's at every feature's close: review this directory and the diff against `main`; `make command-log` once the session is closed; merge `020-core-orchestrator-split` into `main` and push `origin`; `converge` follows.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: T001 first; T002 at `analyze`, before Phase 4's first run.
- **Foundational (Phase 2)**: T003 before any Go change (Run 3); T004, T005 and T006 in
  parallel after T001 and T003.
- **The core's shape (Phase 3)**: after T004 and T005. T007 → T008 → T009; T010 after T005;
  T011 after T003; T012 after T007–T010.
- **The toolchain (Phase 4)**: after T002; T013 → T014. Never laned (the venv is made on
  the host).
- **The adapter (Phase 5)**: after Phase 4. T015 → T016 → T017 → T018 → T019 → T020 → T021;
  T020 and T021 while the Go reader stands.
- **The flows (Phase 6)**: after Phase 5 and T010 (`twin.diff`), T011 (`12`). T022 after
  T003; T023 and T024 together; T025 after T022–T024; T026 after T025; T027 after T026;
  T028 after T027, while the Go handlers stand.
- **The checks and the scripts (Phase 7)**: after Phase 6. T029 and T030 together; T031
  after T027 and T030.
- **The removal (Phase 8)**: after T021 and T028 (compared) and T022 (the goldens held).
  T032 → T033 → T034 → T035 → T036.
- **The documents (Phase 9)**: after Phase 8. T037 and T038 together.
- **The import (Phase 10)**: T039 after Phase 9, before T040.
- **Live (Phases 11–12)**: after T039, from a commit. T040 → T041 → T042 → T043; T042
  never beside a twin, and T043 never beside T042.
- **Records (Phase 13)**: after Phase 12. T044 and T045 together; T046 after them; T047
  after T046; T048 last.

### Within a phase

Pure code is gated in tier 1 before its tier-2 or live proof. A story's test names the
scenario it proves. A defect a test finds is fixed in that phase, in the package that holds
the behaviour, before the checkpoint; a live task's defect gets a tier-1 test that pins it.
`T007 → T008 → T009; T010, T011 any time after T005 and T003; T012 last in Phase 3;
T015 → … → T021; T022 ∥ (T023, T024) → T025 → T026 → T027 → T028; T029 ∥ T030 → T031;
T032 → T033 → T034 → T035 → T036; T037 ∥ T038; T044 ∥ T045 → T046 → T047 → T048`.

### Parallel opportunities

- Phase 2: T005 beside T004 — Run 5 ∥ Run 4; T006 beside the core's first run — Run 7 ∥
  Run 6.
- Phase 3: T012 beside T011 — Run 11 ∥ Run 10.
- Phase 6: T023 and T024 beside T022 — Run 21 ∥ Run 20.
- Phase 7: T030 beside T029 — Run 27 ∥ Run 26.
- Phase 9: T038 beside T037 — Run 35 ∥ Run 34.
- Phase 13: T044 and T045 together, in one run.

### Parallel example: the foundation

```text
Run 4   internal/*/testdata/contracts/016-probes/, the contract016 constants        (T004)
Run 5   internal/findings/finding.go, contracts/findings.schema.json               (T005)
Run 6   docs/roadmap.md                                                            (T006)
Run 7   internal/provision, internal/server/run.go, internal/api                   (T007)
→ Run 5 beside Run 4, Run 7 beside Run 6
```

---

## Implementation Strategy

**Incremental delivery**: Phase 2 captures the oracle before the implementation it is
taken from can change; Phase 3 gives the core what the orchestrator needs while every old
operation still works; Phases 4–6 build the orchestrator beside the Go code it replaces
and compare the two; Phase 7 turns the checks and the scripts; Phase 8 removes what has
been compared; the rest proves and records. **The MVP checkpoint** is the end of Phase 6:
the orchestrator rehearses through the core's API in tier 2 while the core still serves
everything, so the split can be shown before anything is removed. The one criterion is
Phase 12's T043.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

**Grouping rule.** A run is the tasks that share one context: one package with its tests,
or one document set. Its ids need not be contiguous. A run names at most eight files under
`Read first:`; a records run names at most four documents. Split a run that would exceed
either, since a run that reads five packages fills its context and a run of nine record
tasks exhausts its budget.

**Lane rule.** `[∥ Run M]` after `**Run N**` says Run N may run beside Run M, in its own
worktree, merged back in route order. Mark it only when the two runs edit disjoint files
and read disjoint `Read first:` sets, no edge in Dependencies joins them, neither names
tier 2, tier 3, a hand scenario or the host, and neither carries `[operator]` or `[live]`.
`analyze` checks each mark.

**Line grammar**, which `scripts/converge-loop.sh` parses:

```
N. **Run N** [∥ Run M] — <what the run builds> (T0xx–T0yy, T0zz). Read first: path/a.go, path/b_test.go. Only these; stop and report.
```

An `[operator]` or `[live]` run says so in place of "Only these": `**Run N** — [live] …
(T0xx). Stop and report.`

1. **Run 1** — the baseline: the pure gates and the tree's and the host's state read (T001). Read first: Makefile. Only this; stop and report.
2. **Run 2** — [operator] the constitution amended to 3.0.0 as drafted and as analyze took it, the plan template with it (T002). Stop and report.
3. **Run 3** — [live] the three documents' goldens captured from the running Go build on a throwaway proposed change, before any Go changes (T003). Stop and report.
4. **Run 4** — the 016 shapes frozen and the contract016 constants (T004). Read first: internal/findings/frozen_contracts_test.go, internal/server/helpers_test.go, internal/cli/create_test.go, internal/lab/twin_test.go, internal/findings/snapshot_test.go. Only this; stop and report.
5. **Run 5** [∥ Run 4] — the core's five run identifiers and three operations in the findings schema (T005). Read first: internal/findings/finding.go, internal/findings/finding_test.go, contracts/findings.schema.json, specs/020-core-orchestrator-split/data-model.md. Only this; stop and report.
6. **Run 6** — the roadmap reconciled: F-027's row, Release 0.3's total and item 5 (T006). Read first: docs/roadmap.md, specs/020-core-orchestrator-split/brief.md. Only this; stop and report.
7. **Run 7** [∥ Run 6] — Describe, run.read and run.interrupt over the history reads, replayed on the seven histories (T007). Read first: internal/provision/client.go, internal/provision/types.go, internal/server/follow.go, internal/server/handlers.go, internal/api/wire.go, internal/api/client.go, internal/server/follow_test.go, contracts/api.md. Only this; stop and report.
8. **Run 8** — detach on the four runs, and the core CLI's --detach and run read|interrupt (T008, T009). Read first: internal/server/create.go, internal/server/provision.go, internal/server/step.go, internal/server/destroy.go, internal/server/streams.go, internal/cli/create.go, internal/cli/root.go, internal/cli/send.go. Only these; stop and report.
9. **Run 9** — twin.diff: two snapshots compiled on the goldens' path and the step between them, with its CLI (T010). Read first: internal/server/compile.go, internal/server/snapshot.go, internal/server/step.go, internal/step/plan.go, internal/step/diff.go, internal/cli/compile.go, contracts/step.schema.json, testdata/snapshot/three-node-probed.json. Only this; stop and report.
10. **Run 10** — twin.json 12: the stage and rehearsal blocks gone, the step's rule from the two envelopes, an 11 shown and refused (T011). Read first: internal/lab/twin.go, internal/lab/wire/types.go, contracts/twin.schema.json, internal/server/show.go, internal/server/step.go, internal/lab/twin_test.go, internal/server/step_test.go, internal/cli/show_test.go. Only this; stop and report.
11. **Run 11** [∥ Run 10] — the API schema's new arguments and frames, and api.md's and cli.md's gained operations (T012). Read first: contracts/api.schema.json, contracts/api.md, contracts/cli.md, internal/api/wire_test.go, specs/020-core-orchestrator-split/contracts/README.md. Only this; stop and report.
12. **Run 12** — the orchestrator's toolchain: the project, the venv, make, the lane seed and CI (T013, T014). Read first: Makefile, .github/workflows/ci.yml, .github/workflows/release.yml, scripts/converge-loop.sh, scripts/tests/test_converge_loop.py, specs/020-core-orchestrator-split/research.md. Only these; stop and report.
13. **Run 13** — the adapter's snapshot module: normalize, the hashed bytes and the id, held to the four fixtures' ids (T015). Read first: internal/snapshot/snapshot.go, internal/snapshot/json.go, internal/ctm/forms.go, internal/ctm/json.go, internal/ctm/types.go, testdata/snapshot/three-node.json, docs/verified-facts.md. Only this; stop and report.
14. **Run 14** — the adapter's client, schema check, packages and intrinsic validation (T016). Read first: internal/intent/client.go, internal/intent/schemainfo.go, internal/intent/conformance.go, internal/intent/mapping.go, internal/validate/rules.go, internal/validate/validate.go, internal/psp/pattern.go, psp/nokia_srlinux.yaml. Only this; stop and report.
15. **Run 15** — the adapter's read: the eleven queries, the mapping, the stamps, the events and the probes (T017). Read first: internal/intent/queries.graphql, internal/intent/project.go, internal/intent/stamps.go, internal/intent/events.go, internal/intent/probes.go, internal/intent/artifact.go, internal/intent/completeness.go, internal/intent/cable.go. Only this; stop and report.
16. **Run 16** — the adapter's stages: the reference, the resolution, the staleness rules, the list and the target (T018). Read first: internal/stages/ref.go, internal/stages/resolve.go, internal/stages/stale.go, internal/stages/list.go, internal/stages/target.go, internal/stages/blocks.go, internal/stage/stage.go, internal/server/resolve.go. Only this; stop and report.
17. **Run 17** — the adapter's three commands, the findings document and rules, and the stages text to its golden (T019). Read first: internal/findings/render.go, internal/findings/finding.go, internal/server/console.go, internal/cli/stages.go, internal/cli/read.go, internal/cli/schema.go, orchestrator/tests/golden/README.md, orchestrator/tests/golden/stages.txt. Only this; stop and report.
18. **Run 18** — tier 2, the reader's ported tests, seeded through the fixture tool, each run alone (T020). Read first: internal/intent/read_contract_test.go, internal/intent/conformance_contract_test.go, internal/intent/defects_contract_test.go, internal/server/probes_contract_test.go, internal/cli/probes_contract_test.go, internal/cli/schema_contract_test.go, cmd/fylgja-fixture/main.go, internal/testsupport/infrahub.go. Only this; stop and report.
19. **Run 19** — tier 2, the stages' ported tests and the byte-for-byte compare with the Go reader, each run alone (T021). Read first: internal/stages/stages_contract_test.go, internal/stage/artifact_contract_test.go, internal/stage/mixed_contract_test.go, internal/stage/reproducibility_contract_test.go, internal/server/snapshot_contract_test.go, internal/testsupport/proposed.go, cmd/fylgja-fixture/main.go, orchestrator/tests/contract/conftest.py. Only this; stop and report.
20. **Run 20** — the plan, rehearsal and deadline documents, held to the goldens (T022). Read first: internal/rehearsal/verdict.go, internal/rehearsal/report.go, internal/rehearsal/markdown.go, internal/rehearsal/deadline.go, internal/stages/plan.go, contracts/rehearsal.schema.json, orchestrator/tests/golden/README.md, orchestrator/tests/golden/rehearsal.md. Only this; stop and report.
21. **Run 21** [∥ Run 20] — the core's client over the detached shape, and the record and store with the trust and reclaim rules (T023, T024). Read first: internal/api/client.go, internal/api/wire.go, internal/cli/failures.go, internal/server/rehearse.go, internal/snapshot/store.go, internal/stages/target.go, specs/020-core-orchestrator-split/data-model.md. Only these; stop and report.
22. **Run 22** — the five flows: read, schema check, create, step and plan (T025). Read first: orchestrator/src/fylgja_orchestrator/core.py, orchestrator/src/fylgja_orchestrator/record.py, orchestrator/src/fylgja_orchestrator/documents/plan.py, orchestrator/src/fylgja_orchestrator/adapters/infrahub/__main__.py, internal/server/stages.go, internal/server/create.go, internal/server/step.go, internal/cli/step.go. Only this; stop and report.
23. **Run 23** — the rehearse flow: plan, reclaim, baseline, steps, verdicts, the posted report, the deadline and the finally (T026). Read first: internal/server/rehearse.go, internal/provision/workflow_rehearse.go, infrahub/checks/fylgja_api.py, orchestrator/src/fylgja_orchestrator/flows/twin_create.py, orchestrator/src/fylgja_orchestrator/flows/stage_plan.py, orchestrator/src/fylgja_orchestrator/documents/rehearsal.py, orchestrator/src/fylgja_orchestrator/documents/deadline.py, specs/015-proposed-change-rehearsal/research.md. Only this; stop and report.
24. **Run 24** — fylgja-cli and the runner (T027). Read first: internal/cli/root.go, internal/cli/send.go, internal/cli/failures.go, internal/cli/stages.go, internal/cli/rehearse.go, orchestrator/src/fylgja_orchestrator/flows/__init__.py, orchestrator/pyproject.toml. Only this; stop and report.
25. **Run 25** — tier 2, the flows against the real Infrahub and a core server with no Infrahub credential, each run alone (T028). Read first: internal/server/rehearse_contract_test.go, internal/server/snapshot_contract_test.go, scripts/e2e.sh, orchestrator/tests/contract/conftest.py, orchestrator/src/fylgja_orchestrator/cli.py, cmd/fylgja-fixture/main.go, specs/020-core-orchestrator-split/research.md. Only this; stop and report.
26. **Run 26** — the checks as the platform's clients, their contract and the Go precheck (T029). Read first: infrahub/checks/fylgja_api.py, infrahub/checks/fylgja_step.py, infrahub/checks/fylgja_twin.py, .infrahub.yml, internal/checks/checks_contract_test.go, specs/015-proposed-change-rehearsal/contracts/checks.md, specs/020-core-orchestrator-split/research.md. Only this; stop and report.
27. **Run 27** [∥ Run 26] — the override's variables, .env.example, the bring-up part and the loopback-only serve (T030). Read first: scripts/bring-up.sh, scripts/infrahub/docker-compose.override.yml, .env.example, Makefile. Only this; stop and report.
28. **Run 28** — scripts/e2e.sh through fylgja-cli, case 9's precheck and the greps, checked offline (T031). Read first: scripts/e2e.sh, orchestrator/src/fylgja_orchestrator/cli.py, scripts/bring-up.sh, specs/020-core-orchestrator-split/research.md. Only this; stop and report.
29. **Run 29** — the server's removal: the five handlers, the five arguments, serve with no Infrahub (T032). Read first: internal/server/handlers.go, internal/server/server.go, internal/server/options.go, internal/server/create.go, internal/server/step.go, internal/api/wire.go, cmd/fylgja/serve.go, cmd/fylgja/serve_test.go. Only this; stop and report.
30. **Run 30** — the CLI's removal: the lost nouns and flags, each ending unknown (T033). Read first: internal/cli/root.go, internal/cli/create.go, internal/cli/step.go, internal/cli/harness_test.go, internal/cli/gone_test.go, internal/cli/main_test.go. Only this; stop and report.
31. **Run 31** — the worker's removal: three workflows, the rehearsal's client surface gone, the seven replays (T034). Read first: internal/provision/worker.go, internal/provision/client.go, internal/provision/types.go, internal/provision/options.go, internal/provision/worker_test.go, internal/provision/determinism_test.go, internal/lab/wire/types.go, cmd/fylgja/worker.go. Only this; stop and report.
32. **Run 32** — the reader packages and internal/rehearsal gone, genqlient with them, the retired identifiers, the two boundary tests, the compare tests removed (T035). Read first: internal/compiler/purity_test.go, internal/findings/finding.go, internal/findings/finding_test.go, internal/findings/render.go, Makefile, .github/workflows/ci.yml, go.mod, internal/testsupport/infrahub.go. Only this; stop and report.
33. **Run 33** — the contracts' prose: api.md's and cli.md's losses, orchestrator.md, the 014 and 015 pointers (T036). Read first: contracts/api.md, contracts/cli.md, contracts/checks.md, specs/020-core-orchestrator-split/contracts/README.md, specs/014-proposed-change-stages/contracts/stage-commands.md, specs/015-proposed-change-rehearsal/contracts/rehearse-command.md. Only this; stop and report.
34. **Run 34** — architecture, the C4 model and make diagrams, development.md (T037). Read first: docs/architecture.md, docs/c4/workspace.dsl, docs/development.md. Only this; stop and report.
35. **Run 35** [∥ Run 34] — the glossary, the brief, the README, SECURITY.md (T038). Read first: docs/glossary.md, docs/brief.md, README.md, SECURITY.md. Only this; stop and report.
36. **Run 36** — [operator] the checks on origin's main, imported, both task workers' checkouts read (T039). Stop and report.
37. **Run 37** — [live] the five processes from this tree, the task workers recreated with the override and read from inside, research §4's measurements, then the hand scenarios of quickstart §2–§6 (T040, T041). Stop and report.
38. **Run 38** — [live] the contract tier whole through the platform on the bridge, then tier 3 whole on a quiet host (T042, T043). Stop and report.
39. **Run 39** — the records: verified-facts.md, the roadmap's F-027 built, CLAUDE.md, then the closing gates and greps (T044–T047). Read first: docs/verified-facts.md, docs/roadmap.md, CLAUDE.md, specs/020-core-orchestrator-split/quickstart.md. Only these; stop and report.
40. **Run 40** — [operator] the operator's review, merge, push and the command log (T048). Stop and report.

`converge` follows Run 40.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route"
only up to the next heading.

**For `analyze` to settle**: the eight decisions of the header, and the route's six lane
marks. On the marks: Run 5 ∥ Run 4 edits disjoint files (the frozen copies and the
`contract016` constants against `finding.go`, `finding_test.go` and the findings schema)
with disjoint reads, `data-model.md` dropped from Run 4's list at `analyze` so they are; Run 7 ∥ Run 6 the same (the roadmap against `internal/provision`,
`internal/server/run.go` and `internal/api`); Run 11 ∥ Run 10 (the API schema and the two
prose contracts against `internal/lab`, `show.go`, `step.go` and the twin schema; T012
leaves `twin.json` `12`'s prose to T036); Run 21 ∥ Run 20 (`core.py` and `record.py`
against `documents/`); Run 27 ∥ Run 26 (the scripts against `infrahub/checks/` and
`internal/checks`); Run 35 ∥ Run 34 (`make diagrams` writes `docs/c4/` and reaches Docker
for two pinned images, nothing of the host's processes, as 016's Run 23 did). Run 12 is
never laned: it makes `orchestrator/.venv` on the host, which a lane's worktree would not
carry back.

**What a run should know that no task line carries**:

- **Three stops are expected under a headless loop**: Run 3 (`[live]`, the goldens), Run
  36 (`[operator]`, the import) and Run 37–38 (`[live]`); attended, the live sessions run
  Runs 3, 37 and 38 and the operator answers Runs 2, 36 and 40 in the chat.
- **The goldens are the oracle**: a run that finds a golden wrong fixes the renderer, never
  the golden, unless the operator says the Go output was wrong, which is an `[operator]`
  task converge adds.
- **Port, compare, remove**: Runs 18, 19 and 25 compare against the Go reader and handlers
  through the host's running server (016's build until Run 37; this tree's code for those
  handlers, unchanged by Runs 7–11). Run 32 may not start until each of those runs has
  recorded a green compare in research §5.
- **T039 moves `origin/main` mid-chain.** A moved remote-tracking ref stops the loop at
  `contract`; the operator does the push and the import while the loop is paused at Run
  36, as 016's T041 did.
- **`make test`'s budget**: T013 measures the Python tests' share; if `pytest` alone adds
  more than about 8 s (Prefect's import), the flows' modules import Prefect lazily and the
  unit tests call the flow functions plain; T047 decides whether the 65 s budget moves.
- **The Python tier 2 shares one Infrahub with the Go tier**: `make test-contract` runs it
  after `internal/checks`; a loop session running one of its tests alone runs it with no
  Go contract package at the same time.
- **R-22's estimate** (24–36 hours of sessions) stands against forty runs, three of them
  live and four the operator's; T047 records the measured effort beside it.
- **What no run may do**: boot a twin while tier 2 runs; run tier 2 or tier 3 whole outside
  Run 38; recreate Infrahub's task workers outside Run 37; push; write to `main` but T020's
  probes and T039's import; re-make `local/.env` (T040 appends names); echo a token, the
  auth string or a login.
