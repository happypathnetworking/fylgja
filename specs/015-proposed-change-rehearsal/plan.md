# Implementation Plan: A proposed change rehearsed on a twin

**Branch**: `015-proposed-change-rehearsal` | **Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/015-proposed-change-rehearsal/spec.md`, the
brief ([brief.md](brief.md)), 014's close, [D-040](../../docs/decisions.md#d-040) to
[D-042](../../docs/decisions.md#d-042), [D-044](../../docs/decisions.md#d-044) to
[D-048](../../docs/decisions.md#d-048) and Constitution 1.3.0. Research is in
[research.md](research.md) (§1 verified at this plan, §2 its decisions R-01…R-22, §3 the
four decision entries drafted for the operator, §4 owed at implement), the entities in
[data-model.md](data-model.md), the wire forms in [contracts/](contracts/), the validation
in [quickstart.md](quickstart.md).

## Summary

Release 0.2's second spec rehearses a proposed change on a twin, F-007 and F-008 as one.
`fylgja twin rehearse --branch <b>` (the operation `twin.rehearse`) finds the open proposed
change by its source branch, resolves and compiles every stage as `stage plan` does, builds
the first compiled stage as the **baseline**, verifies it and keeps its findings as the
**baseline findings**, steps the twin through each later stage in order with a verify after
each, stops at the first stage that fails (a divergence, or a finding the baseline did not
have), and destroys the twin whatever happened. One **deadline**, the stages' budgets
summed from the node plans under a ceiling of an hour, bounds the run; past it the stage in
progress is cancelled and the destroy follows. The run is a fifth workflow,
`fylgja-rehearse`, whose children are the provision, step and destroy workflows under their
fixed ids, so one twin at a time holds as it does by hand. The report is a `rehearsal`
block in the findings document, its text, and a third rendering, **markdown**, with a table
of the stages and a Mermaid drawing of the steps. Two Infrahub checks run it from a proposed
change: `fylgja-step` asks for the plan and concludes in seconds; `fylgja-twin` asks for the
rehearsal, posts the markdown as a comment on the proposed change, and concludes by the
report's status alone, skipping a draft. To be reached from Infrahub's task workers the
server listens on the host's Docker bridge beside loopback (`--listen`, repeatable), the
Compose override gives the task workers `host.docker.internal` and the two `FYLGJA_API_*`
variables, and the bring-up script starts it so. The twin record moves to `7` to name the
rehearsal that owns a twin, so a dead rehearsal's twin is reclaimed by the next. The API's
and the findings' versions stay `1`; no golden, fixture identifier or other format moves.

Four things the plan found that the spec did not say, each verified live
([research.md §1](research.md#1-verified-at-plan-2026-10-17-development-host)) and decided
here, for `analyze` to settle in the spec:

- **A stage has six verdicts, not five.** The spec's `refused`, `baseline`, `passed`,
  `failed` and `not reached` leave no name for a stage whose step could not run or whose
  wait did not complete: the step rejected by its locks, cancelled before its stage, the
  deadline, an interrupt. That is **`error`** (status `error`, exit 2), distinct from
  `failed` (`nonconforming`, 5), since nothing was learned about the change
  ([R-07](research.md#r-07-a-stages-verdict-is-computed-in-the-workflow-from-the-childs-result-and-the-baselines-wait-the-verifys-counts-ride-on-the-activitys-result),
  [R-08](research.md#r-08-status-and-exit-and-the-identifiers)).
- **The override hard-codes the address and reads the token from `local/.env`.** FR-025
  reads as if both were values the override carries; the address is the name
  `host.docker.internal:7650`, which Docker resolves to the bridge, and the token is
  `${FYLGJA_API_TOKEN}`, which Compose reads from `--env-file local/.env`, so the file in
  the tree holds no value and the task workers are recreated once
  ([R-17](research.md#r-17-the-server-listens-on-every---listen-given-the-override-and-the-bring-up-script-put-it-on-the-bridge)).
- **A timed-out check leaves its validator `in_progress` forever** (research §1.4), so
  `fylgja-twin`'s own deadline must close the answer before Infrahub's: the check interrupts
  the run and concludes inside its `timeout`, and the interrupt from Infrahub's own
  cancellation is sent with a blocking call, since nothing is awaited in that handler
  ([R-16](research.md#r-16-cancellation-from-infrahubs-side-the-interrupt-is-sent-synchronously-and-the-deadline-covers-the-rest)).
- **A branch created before a check's import never runs it** (research §1.5). The checks
  reach the development host's Infrahub only once they are on `origin`'s `main` and imported,
  which is the operator's; tier 3's ninth case runs the live check and so passes only after
  that, and fails naming it before
  ([R-21](research.md#r-21-how-a-check-change-reaches-the-development-hosts-infrahub)).

## Technical Context

**Language/Version**: Go 1.26.0 (`go.mod`), one static binary, CGO disabled, for everything
that decides; Python, as the task-worker image carries it (3.14.7, `infrahub-sdk`'s
`InfrahubCheck`, `httpx` 0.28.1), for the two checks, which are glue on Infrahub's runtime as
the Jinja template is and run in no process of Fylgja's; YAML for `.infrahub.yml` and the
Compose override; JSON Schema 2020-12 for `contracts/rehearsal.schema.json` and the moved
`twin.schema.json`; bash for `scripts/e2e.sh` and `scripts/bring-up.sh`; GitHub-flavoured
Markdown with a Mermaid block for the comment; Markdown for the records.

**Primary Dependencies**: the Temporal Go SDK v1.49 (child workflows under
`ChildWorkflowOptions` with the fixed ids, `workflow.NewTimer` for the deadline, cancellation
through the children's context, `workflow.NewDisconnectedContext` for the destroy, the test
suite's `OnWorkflow` fakes for the children); Infrahub 1.11.2 (the proposed-change pipeline
that runs user checks at creation and on `CoreProposedChangeRunCheck(USER)`, `CoreUserValidator`
and `CoreStandardCheck`, `CoreChangeThread` and `CoreThreadComment`, `InfrahubReadOnlyRepositoryImportLastCommit`,
the Prefect task timeout a check's `timeout` becomes); Docker 29.8.1 with Compose 5.6.0
(`extra_hosts` with `host-gateway`, `${VAR}` from `--env-file`); containerlab 0.79.0
(unchanged); cobra for `twin rehearse`, `--markdown` and `--listen`; the OpsMill skill
`infrahub-managing-checks` (loaded; below).

**Storage**: files only, as before (IX): the bundle store, the twin directory (`twin.json`
`7`), Temporal history (one more workflow's). Infrahub holds the comments, the validators and
the check nodes, its own records of its pipeline, which Fylgja never reads. No database.

**Testing**: tier 1 (`make test`) with `internal/rehearsal`'s pure tests (verdict, deadline,
markdown, reproduce, the block against its schema, purity), the workflow under the test
suite with the three children faked (every stage passes; a stage fails; the baseline not
built; a step rejected; the deadline cutting a step and destroying; cancellation; an unclean
destroy; one stage), the nine recorded histories replaying unchanged, `twin.json` `7` and
the frozen `6`, the API's `markdown` frame, the harness over `twin rehearse` and its
refusals, `--listen` repeated, the boundary test, and a test that `.infrahub.yml` registers
both checks with their files present; tier 2 (`make test-contract`) against the real
Infrahub: `internal/checks` serves the tree's checks from the bridge under a test-only
registration, opens a draft on a throwaway branch and reads both checks' conclusions and
messages (the draft skipped; the plan passed; a stale mark refused), skipping where the
task workers reach no server (CI), and `internal/server` proves a refused stage never dials
the workflow service; tier 3's ninth case runs the live checks through the operator's
server: the draft skipped, a rehearsal passed with its comment, a stage made to fail at push
with its comment, and nothing left. Tier 1 stays under 45 s (no infrastructure); tier 2
gains about four minutes (one registration's import at about 21 s, one pipeline of about
50 s, two re-runs of about 20 s, the rebase and the deletes); tier 3 gains about five
minutes (one rehearsal passed at about three, one failed at about two, two pipelines).

**Target Platform**: the development host (Ubuntu 26.04.1, the one Infrahub install, `main`
at `e43a1cde…`, docker0 `172.17.0.1/16`, the Compose network `172.18.0.0/16`) and CI's
`ubuntu-26.04` runner, whose `--part infrahub` brings up an Infrahub whose task workers reach
no Fylgja server, so the check test skips there and says so.

**Project Type**: a feature of an existing single-binary Go project with a bash test tier,
Markdown records, and, new, Python glue that Infrahub runs from this repository.

**Performance Goals**: the fixture's four stages rehearse in about three minutes on this host
(a create of about 50 s, a verify of about 5 s, a step of about 15 s and an unchanged one of
about 10 s with their waits, a destroy of about 3 s) against a deadline of 1,980 s; a
rehearsal is bounded by that deadline and the ceiling of 3,600 s; `fylgja-step` concludes
within a minute of a run-check (SC-005); `fylgja-twin` concludes inside its 4,200 s timeout
every time, the destroy included (SC-006). No activity budget changes.

**Constraints**: one twin at a time, held by the children's fixed ids and the host check
(VII); the rehearsal's workflow is bounded by its deadline and ends in its destroy, with no
signal and no TTL, and is the decision entry D-051's to admit (VIII); Fylgja writes nothing
to Infrahub, and the one write, the comment, is the check's, a client (III, XI); every
refusal the server's, the check's conclusion a mapping of the document's status alone (XI);
no credential in any report, comment, message, log line, record, history or test output,
and the token crosses the bridge in the clear on purpose, said in `SECURITY.md` (X, FR-035);
no `at` of Fylgja's own (VI, unchanged); the API's version and the findings' stay `1`, and no
golden, fixture identifier or other format moves (FR-031); no twin while tier 2 runs, which
the check test honours by rehearsing nothing; a session never pushes, so the checks reach
the host's Infrahub on the operator's push and import (R-21).

**Scale/Scope**: one new package of product code (`internal/rehearsal`, about 600 lines and
as many of tests) and one of tests (`internal/checks`); one workflow with its input and
result types and its test suite (about 500 lines in `internal/provision`); one handler
(`internal/server/rehearse.go`, about 400 lines) and one command; `twin.json` `7`, the
record and the frozen `6`; three Python files (about 350 lines) and one query; one contract
added (`rehearsal.schema.json`) and six amended (`findings`, `show`, `verify`, `step`,
`api`, `twin`); `--listen`, the override, two parts of the bring-up script, `SECURITY.md`,
`.env.example`; the fixture tool (three flags) and test support (eight helpers); one tier-3
case of about 250 lines of bash; four decision entries; about fourteen records. The live
parts (the task workers recreated, the server on the bridge, the push and the import, tier
3) are the operator's or a live session's.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 1.3.0 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. Everything that decides is Go in the one binary: the stages, the baseline, the deadline, the verdicts, the report and its three renderings, the run. The two checks are Python because Infrahub runs a check in its own task workers from a class of its SDK, as it renders the template from Jinja: they are glue on Infrahub's runtime, no process of Fylgja's runs them, and the critical path (server, worker, client) carries no second runtime. They hold one rule, FR-017's exception for a branch point refused `contract.node.missing`, read from the finding's rule and `at_source` (D-052); every other conclusion is the document's status, mapped, and the comment is the markdown the server rendered. No Python test framework is added: the checks are proven inside Infrahub by a Go contract test (R-18), and the OpsMill skill's YAML test framework is not used. Nothing new is embedded. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness from the PSP | **PASS**. No compiler, PSP or platform change. The deadline is summed from the node plans' budgets, each the package's (deploy, readiness, push, destroy), the largest over a stage's nodes, plus the mechanism constants that already bound each activity; the ceiling (3,600 s) and the check's timeout (4,200 s) bound the whole run and are not a platform's. `internal/rehearsal` joins `TestCompilerNamesNoPlatform`'s list. A mixed twin rehearses as a single-vendor one does. |
| III | Queries only the Fylgja generics; never past a generic; least demanded; graduate-don't-gate; `iftype` is kind, `mgmt_only` is the use-flag; unimplemented `iftype` rejects; conformance and completeness checked separately | **PASS**. The server reads nothing it did not read for `stage plan`; `readonly_test.go` is unchanged. The checks read `CoreProposedChange` by its source branch and write one `CoreChangeThread` holding one `CoreThreadComment` (D-053, superseding D-049's `CoreChangeComment`), Infrahub's own units, through the task worker's own client, as a client of Fylgja and never as Fylgja: the write is a check's, on the proposed change the check runs for, and D-049 and D-053 admit it beside D-044's read-only registration. The checks demand nothing of anyone's model: their query is `{ Branch { name } }`. |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. Untouched: the rehearsal's steps push the artifacts Infrahub rendered at each stage, as `twin step` does; the failing stage is made by an interface the device does not have, rendered by Infrahub's template, which the node refuses (R-14). The markdown carries no configuration line and no device diff. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **PASS**. The stages compile through `stages.Plan`, as `stage plan` does. `internal/rehearsal` is pure in `step`'s shape (no I/O, no clock, no environment; `TestRehearsalIsPure`), and its markdown is a function of the document and the plan's step pairs, since the block holds no step's changes. The goldens and the fixture's `47b2c449…` do not move (FR-031, SC-011). |
| VI | Provenance recorded (branch, `at`, schema hash, contract version in the bundle; `observed_at` in the CTM envelope and `twin.json`, never in the bundle); `at` passed verbatim or not at all | **PASS**. Every stage is a 014 stage, pinned as 014 pins it; `resolved_at` is the plan's first `observed_at`, informational, heading the report and the comment so a proposed change's comments read in order; the record `7` adds the run that owns the twin and nothing of time. No `at` is composed. |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | **PASS**. The rehearsal creates through the provision workflow under its fixed id and the host check, so a twin of the operator's refuses it as it refuses a create, and the rehearsal's twin refuses the operator's create. Nothing is named per twin or per rehearsal: the workflow id is fixed (`fylgja-rehearse`), the lab is `fylgja`, the twin directory is the one. A dead rehearsal's twin is reclaimed through the destroy workflow, never by a path of its own, and only when the record names a rehearsal run that is not running (R-04). |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **PASS, with the decision entry the principle requires.** A fifth workflow, `fylgja-rehearse`, is introduced: it runs provision, step and destroy as children under their fixed ids, branches only on their results and the pure verdict, reads no clock but the workflow's, and starts no activity of its own; the destroy child runs on a disconnected context from every path, the deadline is a workflow timer, and the children's cancellation is the context's. No activity, budget, heartbeat, version marker or task queue changes, and the nine histories replay. It is not D-007's long-running workflow: it is bounded by a deadline under a ceiling, holds no signal and no TTL, and ends in its destroy. Still, VIII says a long-running workflow MUST NOT be introduced without a decision-log entry, and a run of up to an hour is one by any plain reading, so the entry is drafted (D-051, research §3) for the operator to accept at `analyze`, before the workflow is built, as D-046 was. |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. `twin.json` `7` names the rehearsal that owns the twin; the baseline findings and the verdicts live in the run's history and the document; Infrahub keeps its own comments and validators. Nothing else holds state. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. Nine `rehearsal.*` identifiers (R-08), each with a severity, an exit, a step and a wording in the contract; a branch point passed over is a row that says `refused`, never silent; a draft skipped by `fylgja-twin` says so in its message; the markdown ends with the fidelity caveat. No token, login or password reaches a report, a comment, a message, a log line, a record, a history or a test output: the checks name the address and never the token, the server's log names no address, tier 3's greps cover the comments and the messages (FR-035, SC-008). The token's crossing of the bridge in the clear is stated in `SECURITY.md` (D-050). |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | **PASS**. `twin.rehearse` is an operation (`/v1/twin/rehearse`) with its handler in `internal/server`; `twin rehearse` builds one request and links nothing new; the checks are clients in the constitution's own words ("a check running inside Infrahub"), reaching the core through the API on the bridge with the one token, and every refusal they relay is the server's. The markdown is the document's third rendering, carried in the document frame, not a second representation. The test-only registration and `ServeRepository` are test code. `TestClientReachesTheCoreThroughTheAPIAlone` is unchanged and must still pass. |

**Development Workflow gates**: three tiers (tier 3 never in CI; tier 2 against the real
Infrahub, which the checks need, skipping its check test where Infrahub's task workers
reach no server rather than faking either) **PASS**; verification just-in-time and recorded
(research §1: the bridge and what a task worker reaches, Infrahub's check source and the
Prefect timeout, a check inside a task worker live, what a timed-out check leaves, re-runs
and imports and branches, deletes under comments, the timings; §1.8 lists what is owed at
implement) **PASS**; documents (new glossary terms: rehearsal, baseline stage, baseline
findings, rehearsed stage, verdict, deadline, reclaim; four decision entries drafted,
D-049–D-052, the operator's to accept; `architecture.md` grepped for D-042's default
listener at the close; the C4 model redrawn in the same change) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the generics contract (D-002).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **One flagged**: the fifth workflow, a bounded parent of the three short ones,
through D-051 (row VIII). No signal, no TTL, no database, nothing per twin, no second task
queue, no path around the API: the checks are clients.

**The OpsMill skills**: `infrahub-managing-checks` was loaded for the two checks (research
R-13). Followed: the three components (a `.gql` query registered under `queries:`, a class
with `query = "fylgja_branch"` and `validate()`, a `check_definitions` entry with no
`query:` key); global checks with no `targets` and no `parameters`; `log_error` and
`log_info` alone, since `log_warning` does not exist; a shared module imported relatively,
which the skill allows for a module beside the check; and its rule that a GraphQL rejection
is a `200`, read as the SDK's exceptions on the two reads and the one write. Departed from,
on purpose: no YAML-driven test definitions and no `infrahubctl check` in the tiers, since
this repository has one test framework (Constitution I) and the checks are proven inside a
running Infrahub by a Go contract test; string kinds on the SDK calls rather than generated
protocol classes, since the repository ships no generated module and the two kinds read are
Infrahub's own, not a schema of this repository's; and the skill's cheaper-layer ladder does
not apply, since the checks validate nothing of Infrahub's data and call an external system.
`infrahubctl` is `.venv/bin/infrahubctl`, and neither `uv` nor `poetry` is used.

**Post-design re-check (after Phase 1)**: unchanged. The design adds one workflow (row
VIII, through D-051), one package of pure rules, one operation, one rendering, one record
version and one contract, and moves no gate otherwise. Four places where the design
departs from or refines the spec's text are the plan's to flag and `analyze`'s to settle:
the sixth verdict `error` and its status (R-07, R-08; FR-010–FR-013, the verdict list and
the exit table); FR-025's reading, the override naming the address and Compose carrying the
token (R-17); the check's own deadline inside Infrahub's and the synchronous interrupt
(R-16; FR-021); and tier 3's ninth case passing only once the checks are on `origin`'s
`main` and imported (R-19, R-21; FR-030). Beside them, the four decision entries are
`[operator]` tasks at `analyze`: D-050 before the listener is built, D-051 before the
workflow, D-049 and D-052 before the checks.

## Project Structure

### Documentation (this feature)

```text
specs/015-proposed-change-rehearsal/
├── brief.md                 # the specify brief (committed)
├── spec.md                  # the specification, clarified
├── plan.md                  # this file
├── research.md              # §1 verified at plan (the bridge, Infrahub's check runtime, a live probe, timeouts, re-runs, deletes, timings), §2 R-01…R-22, §3 D-049…D-052 drafted, §4 owed
├── data-model.md            # Phase 1: the rehearsal, a stage's verdict, the baseline findings, the deadline, the record 7, the workflow's input and result, the report, the API, the checks, the server and host, the fixture tool
├── quickstart.md            # Phase 1: the validation scenarios, in the order the work lands
├── contracts/
│   ├── rehearsal.schema.json   # the rehearsal block, to land as contracts/rehearsal.schema.json
│   ├── rehearse-command.md     # twin rehearse; the server's order; the run; statuses and exits; the text and the markdown; the API; show/verify/destroy beside a rehearsal; twin.json 7; the identifiers
│   ├── checks.md               # the two checks: registration, environment, each check's steps, conclusions, the comment, what Infrahub shows
│   ├── server-and-host.md      # --listen; the override; the bring-up script; SECURITY.md; the reclaim and the refusals
│   └── fixture-tool.md         # -ready, -run-checks, -add-interface; the helpers; the tier-2 invariant
├── checklists/requirements.md
└── tasks.md                 # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
internal/rehearsal/                   # NEW, pure (R-11): no I/O, no clock, no environment
├── deadline.go                       # Ceiling (3600 s); Deadline over []DeadlineStage from the node plans and the mechanism constants (R-09)
├── verdict.go                        # Verdict{Refused, Baseline, Passed, Failed, Error, NotReached}; NewFindings by (rule, object) against the baseline's (R-07)
├── report.go                         # Block (the rehearsal block), Reproduce (the commands), the text's stage lines
├── markdown.go                       # Markdown(block): heading, table, Mermaid (quoted labels, #quot; #lt; #gt;, <br/>), stages, warnings, baseline findings, reproduce, the caveat (R-10)
└── *_test.go                         # TestVerdict, TestDeadline, TestMarkdown, TestReproduce, TestBlockValidates, TestRehearsalIsPure
internal/provision/
├── workflow_rehearse.go              # NEW: Rehearse: provision child, VerifyTwin, step children, the deadline timer, the destroy child on a disconnected context; the verdicts (R-01)
├── types.go                          # RehearseInput, RehearseStage, RehearseResult, RehearsedStage; StepResult.WaitCounts; ProvisionInput.Rehearsal
├── client.go, worker.go              # StartRehearse, ResultOfRehearse, the fixed id; StartDestroy cancels a rehearsal first; StartProvision/StartStep refuse beside one; InFlight lists it with its child; the fifth registration
├── activities.go                     # VerifyTwin's result gains Counts (no new activity)
└── workflow_rehearse_test.go, testdata/   # the test suite with faked children; the nine histories replay
internal/lab/
├── twin.go                           # TwinVersion "7"; RecordFields.Rehearsal; NewStepRecord keeps it
├── verify.go                         # the counts on wire.VerifyResult
├── wire/types.go                     # RehearsalRef{WorkflowID, RunID}; VerifyCounts; RecordInput.Rehearsal; TwinRecord.Rehearsal; VerifyResult.Counts
└── testdata/contracts/014-proposed-change-stages/twin.schema.json   # NEW: the frozen 6
internal/findings/
├── finding.go                        # the nine rehearsal.* rules; OpTwinRehearse
├── render.go, verify.go              # RehearsalBlock and its parts; Subject.Rehearsal on show and verify; the markdown field
internal/api/
├── wire.go                           # Operations: twin.rehearse; RenderMarkdown; Frame.Document.Markdown; Start.WorkflowID enum
└── client.go                         # the markdown rendering requested and printed
internal/server/
├── rehearse.go                       # NEW: runTwinRehearse: the plan, the baseline, the deadline, in flight, the reclaim, the host check, the start, the follow with stage lines, the post-run reads, the document (R-02…R-05, R-12)
├── handlers.go, call.go, options.go  # the route; the markdown document frame
├── destroy.go, create.go, step.go, show.go, verify.go   # cancelling a rehearsal; refusals beside one; the rehearsal's lines
internal/cli/
├── rehearse.go                       # NEW: twin rehearse --branch [--markdown] [--json]
├── root.go, send.go                  # the render; --markdown exclusive with --json
└── harness_test.go                   # the command (the import test is internal/compiler/purity_test.go, unchanged)
cmd/fylgja/serve.go                   # --listen repeatable: the checks, the listeners, one http.Server, the unencrypted line (R-17)
internal/checks/                      # NEW, tier 2 only (build tag contract): TestChecksInsideInfrahub through a test-only registration served from the bridge; skips where the task workers reach no server (R-18)
internal/testsupport/
├── proposed.go                       # MarkReady, RunUserChecks, UserChecksOf, CommentsOf, AddInterface
└── repository.go                     # NEW: ServeRepository, BridgeAddress, DeleteRepository, CheckDefinitions
cmd/fylgja-fixture/main.go            # -ready, -run-checks <artifact|user>, -add-interface (R-20)
infrahub/
├── checks/fylgja_api.py              # NEW: the shared glue: the variables, the request and its frames, the proposed change, the comment, the interrupt
├── checks/fylgja_step.py             # NEW: FylgjaStep (timeout 300)
├── checks/fylgja_twin.py             # NEW: FylgjaTwin (timeout 4200)
└── queries/branch.gql                # NEW: fylgja_branch
.infrahub.yml                         # the query and the two check_definitions (R-13)
scripts/infrahub/docker-compose.override.yml   # task-worker: extra_hosts, FYLGJA_API_ADDRESS, FYLGJA_API_TOKEN
scripts/bring-up.sh                   # infrahub: up -d on an (re)installed override; fylgja: the bridge address, both --listen, report_ok
scripts/e2e.sh                        # case 9 (R-19); the checks' presence asserted; the greps over comments and messages
contracts/
├── rehearsal.schema.json             # NEW
├── findings.schema.json, show.schema.json, verify.schema.json, step.schema.json, api.schema.json, twin.schema.json   # the block; rehearsal on show/verify; wait_counts; markdown; 7
├── api.md, cli.md                    # "015: the rehearsal"
SECURITY.md, .env.example, README.md, CLAUDE.md, Makefile (no change expected),
docs/architecture.md, docs/c4/workspace.dsl (+ make diagrams), docs/glossary.md, docs/development.md,
docs/verified-facts.md, docs/roadmap.md, docs/decisions.md (the operator's four entries), docs/brief.md
```

**Structure Decision**: the rehearsal's pure rules and renderings are a package of their
own, `internal/rehearsal`, as `step`'s are, importing `findings`, `lab/wire` and `step` and
imported by `provision` (the verdict) and `server` (the deadline, the block, the markdown),
so that the workflow and the handler share one function for each rule and the markdown is
testable with no run. The workflow lives in `internal/provision` beside the four it
orchestrates, since it is one of the worker's and shares their input types. The checks live
under `infrahub/checks/` beside the template and the queries, where D-044's registration
already reads; their tier-2 test is its own package, `internal/checks`, because it needs
the bridge, a served repository and Infrahub's pipeline, which no other package's test
does, and must be skippable as one unit. Its component, imports and description move in
`docs/c4/workspace.dsl`, and `make diagrams` redraws the server's and the worker's views and
adds Infrahub's task worker as the checks' container.

## Order of the work

1. **The formats and the pure package**: `wire.RehearsalRef`, `wire.VerifyCounts`,
   `twin.json` `7` and the frozen `6`, `internal/rehearsal` (the deadline, the verdict, the
   block, the reproduce commands, the markdown) with its tests, `rehearsal.schema.json`,
   the `rehearsal.*` rules and the blocks in `findings`, `api`'s `markdown` frame and the
   schema moves. Checkpoint: `make test` and `make lint` green.
2. **The workflow** (needs D-051 accepted): `fylgja-rehearse` with the test suite's faked
   children over every path, the deadline timer, the destroy on a disconnected context, the
   `Service` additions, `StartDestroy` cancelling a rehearsal, the refusals beside one, the
   nine histories replaying. Checkpoint: `make test`.
3. **The server, the client and the API**: the handler in its order (the plan, the
   baseline, the deadline, in flight, the reclaim, the host check, the start, the follow,
   the post-run reads, the document and the markdown), `twin show`, `twin verify` and `twin
   destroy` beside a rehearsal, `twin rehearse`, `api.schema.json`, the harness tests and
   the boundary test. Checkpoint: `make test`, `make lint`.
4. **The listener and the host** (needs D-050 accepted): `--listen` repeatable and its
   tests, the override, the bring-up script's two parts, `SECURITY.md`, `.env.example`,
   `CLAUDE.md`'s start line; then, live, the task workers recreated and the server restarted
   on both addresses (quickstart §2), verified from inside a task worker. The operator's
   for the Compose step; the server is the session's.
5. **The fixture tool and test support**, then the rehearsal by hand on a `fylgja-test-*`
   branch (quickstart §3): ok, the failing stage, the reproduce commands followed, the
   interrupt, the reclaim, `run.in_flight`. Live; the session's.
6. **The checks** (need D-049 and D-052 accepted): the three Python files, the query,
   `.infrahub.yml`, the tier-1 registration test; `internal/checks` and its registration
   helpers; `make test-contract` (quickstart §4, §5), the contract tier's invariant.
7. **Tier 3 and the walk-through**: case 9 with the checks' presence asserted and the
   greps extended, the README's proposed-change section; then, once the operator has pushed
   and imported the checks (R-21, quickstart §6), `make test-e2e` whole and
   `PLATFORMS=nokia_srlinux` once (quickstart §7). Live; the operator's or a live
   session's.
8. **The records at the close**: architecture (grepped for D-042's loopback default) and
   the C4 model, glossary, development.md, verified-facts.md (research §1), roadmap (F-007
   and F-008 built), `docs/brief.md`, `CLAUDE.md`'s Formats, State and start line, `cli.md`
   and `api.md`, `SECURITY.md` re-read; the four decision entries appended by the operator.

The four decision entries (research §3) are the operator's, each before the item it
admits: D-050 before item 4, D-051 before item 2, D-049 and D-052 before item 6; `tasks`
tags them `[operator]` as 014 did D-046.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None. No gate is violated; the one design the constitution says to flag, a workflow that
can run for up to an hour, returns through the decision entry VIII requires (D-051), as
the principle provides.
