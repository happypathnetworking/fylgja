# Tasks: The Infrahub reader reads the schema library's DCIM

**Input**: Design documents from `/specs/017-dcim-reader/`: [plan.md](plan.md),
[spec.md](spec.md), [research.md](research.md) (§1 verified at plan, §2 decisions
R-01–R-22, §3 D-057 and Constitution 2.0.0 drafted, §4 owed at implement),
[data-model.md](data-model.md), [contracts/](contracts/) (`mapping.md`,
`scope-and-commands.md`, `package-matches.md`, `formats.md`, `ctm.schema.json`),
[migration/](migration/), [quickstart.md](quickstart.md); constitution 1.3.0, moving to
2.0.0 at T004; [D-002](../../docs/decisions.md#d-002)–[D-004](../../docs/decisions.md#d-004),
[D-010](../../docs/decisions.md#d-010), [D-028](../../docs/decisions.md#d-028),
[D-045](../../docs/decisions.md#d-045), [D-048](../../docs/decisions.md#d-048),
[D-054](../../docs/decisions.md#d-054).

**Tests**: requested. The brief's Exit, the spec's SC-001–SC-009 and research R-18 name
each tier's cases, and quickstart §1 and §7 name the tests that must exist. Each is a task
below. Every format test validates against the contract file under `contracts/`. The three
goldens move once (T024), on a commit of their own, and maybe a second time at T060 if the
first render differs from the bytes T016 predicted.

**Organization**: the work goes bottom-up, in the plan's order ("Order of the work"),
because every story stands on the same new formats. The identifiers and the package's
matches come first (Phases 2–3), then the scope a request names (Phase 4), then the
template, CTM `2`, the compiler and the formats with the goldens (Phase 5). Then the schema
directory, test support and the fixture tool, ending with the typed client generated from
a branch that holds the library (Phase 6). Then the reader: conformance (US3, Phase 7),
the read with its completeness and omissions (US1 and US2, Phase 8), the step's and the
follow's scope (Phase 9), the stamps and events (US5, Phase 10). Then the host, live
(US6, Phase 11), and the records (Phase 12). The loop runs the pure gates after every
implement run, so every run must leave the tree green: `make build`, static, `make test`,
`make lint` (with tags `contract,fixture,e2e`, so every tagged test must compile after
every run). Story labels mark which story each task builds or proves.

**Orderings this file decides, against the plan's or the spec's text:**

- **The request's scope lands before CTM `2`, and the old reader is bridged for two runs.**
  The plan puts the scope (its item 4) after the reader (item 3). But removing a field
  from `ctm` breaks `internal/intent`'s projection in the same compile, and CTM `2`
  requires `envelope.scope`. So Phase 4 plumbs the scope from the request to
  `intent.Config.Scope` first. T023 then cuts the old generics reader down to CTM `2`'s
  shape, so the tree stays green until T038–T043 replace it. During those runs it records
  the scope it was given and the mapping it really reads (`infrahub-generics`,
  `fylgja-generics`, `0.2`), and still reads every device. No CTM it writes reaches a
  host: nothing live runs before Phase 11.
- **The template is written before the fixture CTMs** (T016 before T019), so that
  `testdata/ctm/three-node.json`'s and `mixed.json`'s artifacts are the new template's
  output, predicted by hand from its text (R-09, R-11). No render is possible on this
  host until the import (T058). T060 compares them with a real render and re-baselines
  again if they differ.
- **Conformance (US3) and the read (US1, US2) are two runs.** For the one run between
  them, the harness's fake Infrahub (`internal/cli/infrahub_test.go`) serves the
  library's schema document beside the generics' GraphQL answers (T037). T043 replaces the
  answers.
- **The new GraphQL operations replace the old ones in the task that switches their
  users.** The interim SDL (T033) carries both the generics and the library, so the old
  stamps operations keep generating until T047 replaces them. The SDL from the migrated
  `main` (T060) then drops the generics.
- **The C4 model is redrawn in the runs that change it**: T034 (the schema and the
  artifacts repository) and T045 (the intent component).

**Tags**: `[operator]` marks a task that needs the operator: a decision entry, the
constitution, a spec amendment, a write to `local/.env`, the go-ahead for `main`'s
migration, a push to `origin`, or the review. `[live]` marks a task that needs the
development host's Infrahub `main`, its server or worker, its twins, or tier 2 or 3
against the migrated host. Unattended, the loop stops at both. Commits are by hand,
conventional, with a body saying why, and end with the model's `Co-Authored-By` trailer.
A session never pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6, from spec.md

---

## Phase 1: Setup (the baseline, the window and the decisions)

**Purpose**: confirm the tree's gates pass on this branch before anything changes, so any
later failure is this feature's own. Then the operator's four gates: the demo window
closed with today's tree, D-057, Constitution 2.0.0, and the plan's departures from the
spec settled.

- [X] T001 Run the pure gates from the repository root and confirm each passes: `make build`; `file bin/fylgja` reports a statically linked executable; `make test` uncached (`GOFLAGS=-count=1`; note the wall time against the 45 s budget, and the load average); `make lint`; `go vet -tags contract,fixture,e2e ./...`; `git diff --stat main -- testdata/golden` is empty. With `local/.env` loaded (in a subshell; its values are quoted), and never printing a token, read from Infrahub (read-only): `main`'s schema hash from `GET $INFRAHUB_ADDRESS/api/schema/summary` (begins `e43a1cde`); `Branch { name }`; on `main`, `FylgjaDevice`, `FylgjaLink` and `FylgjaContract` counts and `fylgja-devices`'s member count (research §1.1 found the demo window open: 3, 3, 1, 3, and `fylgja-test-demo` present); `CoreProposedChange` and `FylgjaStage` counts; `CoreReadOnlyRepository` holds `fylgja` alone; no `Dcim*` kind on `main` (`GET /api/schema?branch=main`). Find the worker and the server with `pgrep -x fylgja` and read each `/proc/<pid>/exe`. Write nothing; report the results in this task's note.
  - *2026-10-25 20:44Z, at `23b07bf`, Run 1 of the converge loop:* every gate passed. `make build`; `bin/fylgja` statically linked. `make test` 33.4 s wall uncached (`GOFLAGS=-count=1`, load average 1.9 before, 3.0 after; 22 packages, `internal/cli` 29.1 s), under 45 s. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; no golden differs from `main`. Infrahub, read with this session's `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` (the loop's sessions hold no node logins, so `local/.env` was not loaded): `main`'s schema hash `e43a1cde…`; `Branch` lists `main` and `fylgja-fixture` alone. **The demo window is closed**, against research §1.1's 18:58Z reading: `main` holds `FylgjaDevice 0`, `FylgjaLink 0`, `FylgjaContract 0`, `fylgja-devices` 0 members, and `fylgja-test-demo` is gone. So T002's after-state already holds; it is the operator's to confirm at Run 2, and its two commands have nothing left to delete. `CoreProposedChange 0`, `FylgjaStage 0`; `CoreReadOnlyRepository` holds `fylgja` alone (`ref main`, commit `3c3e79a`, with the check definitions `fylgja-step` and `fylgja-twin`). `main` has no `Dcim*` kind; its Fylgja kinds are `FylgjaContract`, `FylgjaDevice`, `FylgjaInterface`, `FylgjaLink`, `FylgjaPlatform` and `FylgjaStage`. `pgrep -x fylgja` finds the worker (pid 3052935) and the server (pid 3052957, `--listen`ing on loopback and the bridge), the same pids the plan found. Both run `bin/fylgja` built at `88bc630` with uncommitted changes (`vcs.modified=true`). This run's `make build` replaced the binary (now stamped `23b07bf`), so both now read `(deleted)`. Neither was restarted: the run forbids touching the worker, and the server needs the node logins, which this session does not hold. Both must be restarted from the tree before any live task, and before any tier-2 test that needs the server on the bridge (`TestChecksInsideInfrahub`). 14.6 GiB available. Nothing was written to Infrahub.

- [X] T002 [operator] Close the demo window ([D-054](../../docs/decisions.md#d-054)) **with the tree as it is now**, before any fixture-tool or test-support task (T028–T031) changes the tool, since `-clear-main` reads the generics' kinds (quickstart §0; research §1.1, R-14 step 0): `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-demo -delete`, then `go run -tags fixture ./cmd/fylgja-fixture -clear-main`. Expected: `deleted 3 stages, 1 proposed change, branch fylgja-test-demo`, then the baseline's counts removed; afterwards `main` reads `FylgjaDevice 0`, `FylgjaLink 0`, `FylgjaContract 0`, and `Branch` lists `main` and `fylgja-fixture` alone. The branch is the operator's, so the operator runs it, or answers that a session may. Record the output in this task's note. Blocks T028 and every task that writes to Infrahub (T033 onward).
  - *2026-10-25 20:53Z, at `9bfca40`, Run 2 of the converge loop (live):* **closed by the operator, by hand, at 19:54:38–19:55:00Z**, 26 s after the plan session gave the two commands (its follow-up answered at 19:54:12Z, with no tool call of its own). The fixture tool and test support were then, and are now, `main`'s (`git diff main -- cmd/fylgja-fixture internal/testsupport` is empty), so it was closed with today's tree. The terminal's output was not kept on disk. Infrahub's event log holds what the two lines report: `infrahub.node.deleted` on 3 `FylgjaStage`, then 1 `CoreProposedChange` with its thread, comment, validators and checks, then `infrahub.branch.deleted` at 19:54:45Z (the first line, `deleted 3 stages, 1 proposed change, branch fylgja-test-demo`). Then, on `main`, 3 `NetworkLink`, 12 `NetworkInterface`, 3 `NetworkDevice`, 1 `NetworkPlatform`, 1 `FylgjaContract` and 3 `CoreArtifact` (the second line, `baseline removed from main: 3 links, 12 interfaces, 3 devices, 1 platform, 1 contract`, with the 3 artifacts; the log does not say how many went with their devices). Read again at 20:51Z, writing nothing. `Branch` lists `main` and `fylgja-fixture` alone. On `main`, every baseline kind counts 0, generic and concrete (`FylgjaDevice`, `FylgjaInterface`, `FylgjaLink`, `FylgjaPlatform`, `FylgjaContract`, `NetworkDevice`, `NetworkInterface`, `NetworkLink`, `NetworkPlatform`). So do `CoreArtifact`, `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread`, and `fylgja-devices` has 0 members. `main`'s hash is `e43a1cde…`, and `fylgja` is the only registration, at `3c3e79a`, with `fylgja-step` and `fylgja-twin`. `-clear-main`, run again from this tree, answered `fylgja-fixture: main holds no baseline: nothing to remove` (exit 1, nothing written): the tool's own word that the window is closed. `-branch fylgja-test-demo -delete` was not run again: the branch is gone, so it could only send a `BranchDelete` that Infrahub refuses. T028 and the tasks that write to Infrahub no longer wait on this one.

- [ ] T003 [operator] Put [D-057](research.md#3-1) (the CTM is the contract; a reader maps one source's model onto it; the Infrahub reader reads the schema library's DCIM at `26336e9`; it supersedes D-002, D-003 and D-004) to the operator at `analyze`. If accepted, append it to `docs/decisions.md` as D-057 in D-056's format, after D-056 and before "Parked", with `D-002`, `D-003` and `D-004`'s status lines saying "Superseded by D-057" as earlier supersessions did. Then grep `docs/architecture.md` for the old positions (`generics`, `contract version`, `iftype`, `D-002`, `D-003`, `D-004`) and note each hit's line for T064. If declined, record the answer in `research.md` §5 and build nothing from Phase 5 on: Phases 3 and 4 (the package's matches, the request's scope) stand under 1.3.0; everything from T017 removes what its III mandates. Blocks T017 and T035.
  - *2026-10-25 20:53Z, Run 2 of the converge loop (live): left unchecked.* There is no record of the operator accepting D-057: analyze's report and `23b07bf`'s body leave it to this run, and a headless run cannot ask. Once it is accepted, this is mechanical. `docs/decisions.md` has D-056 at line 3442 and "Parked" at 3493. D-002 (line 129), D-003 (173) and D-004 (224) each read `**Status:** Accepted 2026-09-14`; the one earlier supersession (line 3103) appends `; superseded by [D-053](#d-053) on <date>`. The architecture grep, read now and to be read again after the append, matches 14 lines: `generics` 167, 169, 172, 176, 219, 332, 1413; `contract version` 250; `iftype` 198, 211, 213, 361; `D-002` 167; `D-003` 214; `D-004` 216.

- [ ] T004 [operator] Amend the constitution to 2.0.0 as [research §3.2](research.md#3-2) drafts it, citing D-057: in `.specify/memory/constitution.md`, Principle III rewritten ("The CTM Is the Contract; a Reader Maps One Source"), VI reworded (the scope and the mapping in place of the contract version), II's sentence on the matches, the Gate Adjustments' blessed layer (the mapping, D-057, in place of the generics contract, D-002), the Gate Adjustments' CTM bullet and the Development Workflow's tier gate as research §3.2's two added paragraphs give them, the Sync Impact Report and the version line; in `.specify/templates/plan-template.md` (tracked), the Constitution Check's version and row III's text. After T003; blocks T017 and T035.
  - *2026-10-25 20:53Z, Run 2 of the converge loop (live): left unchecked.* It comes after T003, whose acceptance is not on record, and 2.0.0 is the operator's to accept. Governance requires every decision the constitution cites to be *Accepted*, so D-057 lands first. Checked against 1.3.0: every sentence research §3.2 replaces is in the file word for word. They are VI's "and the contract version" (line 107), the CTM bullet (176–179), the generics-contract bullet (181) and the tier gate (194–195). One thing to settle when it is applied: §3.2 says II "gains" its clause but not where. II's sentence ends "…MUST come from the PSP, never from a global constant." (lines 53–54). The plan template is tracked; its version is at line 43 and row III at line 50.

- [ ] T005 [operator] Settle at `analyze` the plan's four departures from the spec (plan, "Post-design re-check"), and amend `spec.md` where the answer changes its text: (a) `stage list --scope` and `stage.list`'s `scope` argument (R-04), which FR-017 does not name; (b) the migration as two removal documents, implementers first (R-14, research §1.9), where FR-040 says one step; (c) the template's import as the gate before the fixture's re-seed and tier 2, not only before tier 3 (R-14; FR-040); (d) the open demo window as a precondition (T002). With them, tell the operator what FR-040 requires before the work starts: the template, query and checks change needs their push to `origin`'s `main` (T057) before it can be imported; `main`'s schema is migrated (T056); and both fixtures are re-seeded (T060). Record the operator's acknowledgement in this task's note. This file builds the plan's reading of (a)–(d); a different answer changes T012–T014 (a) and Phase 11's order (b, c). `analyze` on 2026-10-25 amended FR-017 (a) and FR-040 (b, c) to the plan's reading, and (d) is T002; what remains here is the telling and the acknowledgement.
  - *2026-10-25 20:53Z, Run 2 of the converge loop (live): left unchecked.* The acknowledgement is the operator's. (a)–(c) stand in `spec.md` as analyze amended them: FR-017 (line 415) names `stage list`, and FR-040 (line 504) gives the two removal documents and the import before the re-seed and tier 2. (d) is T002, now closed. The telling, put to the operator in this run's report: (1) the template, query and checks change reaches Infrahub only after the operator merges the whole branch into `main` and pushes `origin`'s `main` (T057), and it is then imported (T058). The fixtures are re-seeded and tier 2 runs only after that, so `main` carries code that tiers 2 and 3 have not yet proved on this host. (2) `main`'s schema is migrated (T056), this feature's one lasting write to `main`: two removal documents, the reference kinds first, then the library loaded by `-prepare-main`. (3) Both fixtures, `fylgja-fixture` and the mixed one, are deleted and re-seeded in the library's kinds (T060), and their compiled ids move.

**Checkpoint**: baseline green; window closed; D-057 and 2.0.0 accepted before Phase 5.

---

## Phase 2: Foundational — the identifiers

**Purpose**: the sixteen identifiers of R-21, so every later task files them by constant.
The eight retired ones are removed by the tasks that remove their last users (T020, T036,
T042, T050), and T053 checks all eight are gone.

- [ ] T006 [P] In `internal/findings/finding.go`, add the sixteen rule constants of [contracts/scope-and-commands.md](contracts/scope-and-commands.md) "The identifiers" (`scope.invalid`, `scope.unset`, `scope.empty`, `schema.kind.missing`, `schema.field.missing`, `schema.field.mismatch`, `schema.choice.missing`, `schema.used_by.missing`, `platform.missing`, `platform.unmatched`, `omit.cable.ends`, `omit.cable.endpoint`, `omit.cable.outside_scope`, `ctm.version.unsupported`, `psp.matches.missing`, `psp.matches.duplicate`). Each gets the house comment (`// rejection, exit 2, start: <object>; <when>`), with the table's severity, exit, step and object exactly. Register each in `internal/findings/finding_test.go`'s `dataModelRules`. Add `Subject.Scope string` (`json:"scope,omitempty"`) in `internal/findings/render.go`. Give `contracts/findings.schema.json` (still version `1`) `subject.scope` as an optional string matching `^tag:\S+$`, and add a sentence on 017 to its description. Extend `decode_test.go` so it round-trips a subject with a scope. Leave every retired identifier in place.

---

## Phase 3: User Story 4 — A support package says which platforms it is (Priority: P2)

**Goal**: format `0.7`: each package declares `platform.matches`; the registry matches
exactly; the suite refuses no match and a shared match (FR-025–FR-027).

**Independent Test**: both shipped packages pass the suite's pure half with their
matches; `testdata/psp/defects/matches-missing.yaml` and `matches-shared.yaml` fail it by
name; `version-0-6-m11.yaml` is refused naming `0.7`.

- [ ] T007 [US4] Freeze first: copy `psp/nokia_srlinux.yaml` byte for byte to `testdata/psp/defects/version-0-6-m11.yaml`, as `version-0-5-m10.yaml` was kept. Then format `0.7` in `internal/psp/types.go`: `Identity.Matches []Match` (`yaml:"matches" json:"matches"`), `Match{Manufacturer, Platform string}` (`yaml`/`json` `manufacturer`, `platform`), `FormatVersion = "0.7"` (data-model §4). In `psp/psp.schema.json`, and in `contracts/psp.schema.json`, which is byte-identical to it today and stays so: `platform.matches` required, `minItems: 1`, each item `{manufacturer, platform}`, both required, `minLength: 1`, `additionalProperties: false`. Give it the description of [contracts/package-matches.md](contracts/package-matches.md) "The field", including "both exactly, letter case and spacing included". `psp.version.unknown` names `0.7` (`declares format version "0.6", this build understands "0.7"`): pin it with `version-0-6-m11.yaml` in `internal/psp/validate_test.go`, beside the `0.5` case.

- [ ] T008 [US4] The rules and the registry ([contracts/package-matches.md](contracts/package-matches.md) "The rules", "The registry").
  - `psp.matches.missing` in `internal/psp/consistency.go`'s `checkConsistency`: no match, or a pair with an empty name. Object: the package path.
  - `checkDuplicateMatch` over a set of packages: `psp.matches.duplicate`, naming both packages and the pair. `psp validate` runs it over the files given (`internal/server/validate.go`), beside `psp.identity.duplicate`.
  - In `internal/psp/load.go`, `Load` indexes the matches after shadowing and refuses the registry on a shared pair, as it refuses an invalid override, so that `fylgja serve` and `fylgja worker run` refuse at start.
  - `Registry.Match(manufacturer, platform string) (*PSP, bool)`, exact on both strings.
  - Tests in `internal/psp/load_test.go` and `validate_test.go`: exact match; `nokia` / `SR-Linux` and `Nokia` / `SR Linux ` (trailing space) miss; an override sharing a pair refuses `Load`. One case each in `cmd/fylgja/serve_test.go` and `worker_test.go`: a `FYLGJA_PSP_DIR` holding a package that shares a pair refuses the start, naming `psp.matches.duplicate`.

- [ ] T009 [US4] The packages. Move `psp/nokia_srlinux.yaml` and `psp/arista_eos.yaml` to `psp_version: "0.7"`, with `matches: [{manufacturer: Nokia, platform: SR Linux}]` and `[{manufacturer: Arista, platform: EOS}]` (FR-027, R-08). Every `testdata/psp/` package meant to load moves to `0.7` with pairs of its own (`heterogeneous/*.yaml`, `lossy/chassisos.yaml`; for example `FastOS Inc` / `FastOS`), no two sharing one. Every defect under `testdata/psp/defects/` moves to `0.7` with a pair of its own (no two sharing one), so that each still fails by the rule it names and by no other; `version-0-3-m5.yaml`, `version-0-5-m10.yaml` and `version-0-6-m11.yaml` keep their versions. Add `testdata/psp/defects/matches-missing.yaml` (the SR Linux package with `matches: []`) and `matches-shared.yaml` (a third package naming `Nokia` / `SR Linux`). Each must fail its rule in `internal/psp/validate_test.go`'s defect table. `TestShippedPackagesAreValidAndEmbedded` passes at `0.7`.

- [ ] T010 [US4] The conformance suite's pure half (`internal/conformance/pure.go`): the check `matches`, which requires at least one pair with both names non-empty and otherwise says `package <id> (<path>): matches: declared <n> pairs, produced none`. Add `TestShippedPackagesShareNoMatch` in `internal/conformance/pure_test.go`, over every package meant to load (shipped and `testdata/psp/`'s), holding the pairs pairwise distinct. The two defect fixtures of T009 each fail it by name. The boot half is unchanged.

**Checkpoint**: `make test`, `make lint`; packages at `0.7`; nothing reads `matches` yet.

---

## Phase 4: User Story 1, part 1 — the scope a request names (Priority: P1)

**Goal**: `--scope tag:<name>` on five commands, `FYLGJA_DEFAULT_SCOPE` on the server,
the two refusals before any connection, and the scope carried as data to every read.
Nothing filters by it yet (Phase 8 does).

**Independent Test**: through the harness, `intent read --scope fylgja` and `--scope=`
are `scope.invalid` (exit 2), and a request with no scope against a server with no
default is `scope.unset` (exit 2), nothing dialled in either case; `twin step --scope` is
cobra's `unknown flag`.

- [ ] T011 [US1] Create `internal/server/scope.go` with `scopeOf(opts, given string, givenSet bool) (string, error)` (data-model §9). It returns the request's scope when given, else `Server.DefaultScope`. It refuses `scope.invalid` (object the value given; the message names the accepted form `tag:<name>`) for anything not matching `^tag:\S+$`, the empty value included. It refuses `scope.unset` (object `FYLGJA_DEFAULT_SCOPE`; the message names the variable) when neither is set. Both refusals are at step `start`, exit 2. Add `DefaultScope string` to `server.Server` in `internal/server/server.go`. Table tests in `internal/server/scope_test.go`: the default, the argument over the default, `fylgja`, `group:x`, `tag:`, `tag:a b`, `""`, unset.

- [ ] T012 [US1] The API's argument (R-16; [contracts/scope-and-commands.md](contracts/scope-and-commands.md) "The API"). In `internal/server/handlers.go`'s `operationArgs` (wherever the operations' arguments are declared), add `"scope": argString` to `twin.create`, `twin.rehearse`, `intent.read`, `stage.plan` and `stage.list`. `twin.step` with `scope` is `400`, `the request is not one: twin.step takes no argument "scope"`. In `contracts/api.schema.json`, the five operations' `args` gain `scope` (an optional string) with a 017 sentence. The API's version stays `1`. Tests in `internal/api/wire_test.go` and `internal/server/server_test.go`: each frame is valid against the schema, `twin.step`'s refusal, and a `1` client that sends no `scope` is served.

- [ ] T013 [US1] Carry the scope through every read (R-04). In `internal/server/create.go`, `rehearse.go`, `read.go` and `stages.go` (plan and list), call `scopeOf` at `start`: after `--branch`'s and `--stage`'s guards, before the packages load and before any connection. Set `findings.Subject.Scope` on the document. Pass the scope on:
  - `intent.Config.Scope` (`internal/intent/client.go`: the tag's name, after `tag:`);
  - `stage.Read(ctx, branch, at, scope, reg, observedAt)` (`internal/stage/stage.go`);
  - `stages.Stamper.Stamps(ctx, branch, at, scope)`, with `stages.Plan`, `List` and `Resolve` carrying it (`internal/stages/`);
  - `provision.ProvisionInput.Scope`, `ReadIntentInput.Scope` and `ReconcileInput.Scope` in `internal/provision/types.go` (`json:"scope,omitempty"`), the activities passing it to `stage.Read`, and the follow's `ReconcileInput` taking `ProvisionInput.Scope`.

  The old generics reader takes `Config.Scope` and does not filter by it yet. Say so in a comment naming T039. The nine recorded histories in `internal/provision/workflow_replay_test.go` must replay unchanged. Every caller and fake of the changed signatures moves in this task.

- [ ] T014 [US1] The client (`internal/cli/`): `--scope` on `twin create`, `twin rehearse`, `intent read`, `stage plan` and `stage list`, sent as `args.scope` only when given (so `--scope=` is sent as `""` and refused by the server). `twin step` gets no flag, so cobra refuses `--scope` (`unknown flag: --scope`, exit 2, no request). The harness's `server.Server` sets `DefaultScope: "tag:fylgja"`. Tests through the harness for each of the five commands: `scope.invalid` for `--scope fylgja` and `--scope=`; `scope.unset` against a harness server with no default; both before any connection, with nothing dialled (the fake Infrahub and the workflow service record no request). Plus `twin step --scope tag:fylgja` refused by cobra.

- [ ] T015 [US1] The server's setting ([contracts/scope-and-commands.md](contracts/scope-and-commands.md) "The server").
  - `cmd/fylgja/serve.go` reads `FYLGJA_DEFAULT_SCOPE` and reports, after the state root line, `fylgja serve: default scope: tag:fylgja`, or `fylgja serve: default scope: unset (a request that names no scope is refused)` when unset or empty. A value not matching `^tag:\S+$` refuses the start: `fylgja serve: FYLGJA_DEFAULT_SCOPE <value> is not tag:<name>`, exit 2, before it listens. The worker never reads it.
  - Tests in `cmd/fylgja/serve_test.go`: a set default, an unset default and a malformed one.
  - `.env.example` documents the name under the server's variables.
  - `scripts/bring-up.sh` scaffolds `FYLGJA_DEFAULT_SCOPE` as `tag:fylgja` in `env_value`. The script keeps an existing `local/.env` byte for byte, so on this host the name is added by the operator (T055). Read how the script judges an existing file's names (around its `grep -qx FYLGJA_API_TOKEN`), and make a missing `FYLGJA_DEFAULT_SCOPE` a reported note rather than a refusal, since the server starts without it.
  - `shellcheck scripts/bring-up.sh scripts/e2e.sh` is clean.

**Checkpoint**: `make test`, `make lint`; every refusal of the scope proved through the
harness before any connection.

---

## Phase 5: Foundational — the template, CTM 2, the compiler, the formats and the goldens

**Purpose**: the template the fixture CTMs' artifacts come from; CTM `2` with the `1`
frozen; validation and the compiler without `iftype`, every interface a port, the
reader's fidelity list copied; manifest `5` and `twin.json` `8` with the `4` and the `7`
frozen; the old reader bridged; the goldens re-baselined on their own commit.

**⚠️ CRITICAL**: every later phase needs this one. T017–T024 are one run: the tree does
not compile between them.

- [ ] T016 [P] Load the `infrahub:infrahub-managing-transforms` skill, and read its SKILL.md, `rules/queries-union-fragments.md` and `infrahub-common/rules/deployment-gql-dry-run.md` before editing. Apply them where `CLAUDE.md` does not decide otherwise (`.venv/bin/infrahubctl`, no `uv`/`poetry`). Then rewrite, as R-11 and [contracts/mapping.md](contracts/mapping.md) give them:
  - `infrahub/queries/device_config.gql`: research §1.6's template query, `DcimDevice(name__value: $device)` with `description`, `platform { node { name manufacturer { node { name } } } }`, and `interfaces { edges { node { __typename name status role ... on InterfacePhysical { connector { node { connected_endpoints { edges { node { ... on DcimInterface { name device { node { name } } } } } } } } } } } }`.
  - `infrahub/templates/device_config.j2`: one file for both platforms. It takes the EOS dialect when `platform.node.name.value == 'EOS'` and the SR Linux one otherwise (a device with no platform included, so that the pipeline never fails). It renders only interfaces whose `__typename` is `InterfacePhysical`: a management-role port as the comment it is today; any other port configured with its far end's `<device> <port>` as its description, and `shutdown` / `admin-state disable` when `status == disabled`. It renders no loopback and no virtual interface. The header's second line is `# platform <Manufacturer> <Platform>; <description>`.
  - `.infrahub.yml`: the definition's description. The definition itself is unchanged (FR-034).

  `infrahub_yaml_test.go` stays green. Then write in `research.md` a new §5 ("Verified at implement"), §5.1: the exact bytes the template renders for `n1`, `n2` and `n3` of the three-node fixture and for `s1`, `e1` and `e2` of the mixed one (data-model §12, R-15, with `description` `FYLGJA-MARKER-fixture` and the mixed seed's marker), worked by hand from the template's text. Say that they are predicted, to be checked at T060.

- [ ] T017 The CTM's contract files (R-06; [contracts/formats.md](contracts/formats.md) "The frozen copies"). Copy the current `contracts/ctm.schema.json` unchanged to `internal/ctm/testdata/contracts/017-dcim-reader/ctm.schema.json` (the frozen `1`). Then copy [contracts/ctm.schema.json](contracts/ctm.schema.json) (this feature's, `$id …/contracts/ctm/v2`) to `contracts/ctm.schema.json`. Copy the current `testdata/ctm/three-node.json` unchanged to `testdata/ctm/defects/version-1.json` (a `1` fixture, valid against the frozen copy).

- [ ] T018 CTM `2` in `internal/ctm/types.go` and `json.go` (data-model §2):
  - **Changed**: `Envelope{Branch, At, ObservedAt, SchemaHash, Scope, Mapping, Fidelity}`, with `fidelity` sorted by (disposition, object) and written as `[]`, never `null`; `Mapping{Reader, Model, Version}`; `FidelityRow{Disposition, Object, Source, Reason}`; `Platform{Package, Version (omitempty)}`; `Interface{Name, MgmtOnly, Enabled, Link, Provenance}`; `Device` without `Role` and `Site`; `Version = "2"`.
  - **New constants**: `ReaderInfrahubDCIM = "infrahub-dcim"`, `ModelSchemaLibrary = "opsmill/schema-library"`, `ModelVersion = "26336e9"`.
  - **Gone**: the `Iftype*` constants, `KnownIftypes`, `ImplementedIftypes`, `Address`, `Envelope.ContractVersion`, `Normalize`'s `Family` and its address sort. `ContractVersion`, `ContractKind`, `RequiredGenerics`, `DeviceGeneric` and `ArtifactTargetGeneric` stay until their last users go (T036, T042, T048, T053): give each a plain comment naming 017's removal, not a `Deprecated:` marker, which lint would flag.
  - **`Unmarshal`** refuses another `ctm_version`, naming both (`unsupported ctm_version "1", expected "2"`).
  - **Tests in `internal/ctm/json_test.go`**: `TestVersion1IsRefused`, reading `testdata/ctm/defects/version-1.json` (valid against the frozen `1`) and refused naming both versions. `TestCTMFixturesSatisfyContract`, `TestMarshalledCTMSatisfiesContract` and `TestWellFormedDefectFixturesSatisfyContract` over T019's fixtures. The canonical-order and `Normalize` cases moved to the new fields. `TestDeviceFieldOrderFollowsTheContract` on the new device.

- [ ] T019 The fixture CTMs under `testdata/ctm/` move to `2` (R-09): `three-node.json`, `mixed.json`, `lossy.json`, `mgmt-link.json`, `no-mgmt.json`, `observed-later.json`, `two-mgmt.json` and the three `*.shuffled.json`. Each loses `lo0` and every non-port interface, `role`, `site`, `iftype`, `parent` and `addresses`. Each `platform` becomes `{"package": "<platform.id>"}` (`nokia_srlinux`, `arista_eos`, the lossy package's id). The envelope drops `contract_version` and gains `scope: "tag:fylgja"`, `mapping: {reader: "infrahub-dcim", model: "opsmill/schema-library", version: "26336e9"}`, and `fidelity` holding exactly [contracts/mapping.md](contracts/mapping.md) §5's three rows, sorted:
  - `{approximated, interface.enabled, InterfacePhysical.status, "a port is enabled unless its status is disabled; the library's status is not an admin state"}`
  - `{approximated, interface.mgmt_only, InterfacePhysical.role, "the management port is the port whose role is management; the library has no management-only flag"}`
  - `{omitted, platform.version, DcimPlatform, "the library's platform carries no version"}`

  `three-node.json`'s and `mixed.json`'s artifacts (and their shuffled copies') are T016's predicted bytes, with their checksums recomputed as the fixture's own rule computes them. `observed-later.json` still differs from `three-node.json` in `observed_at` alone (`TestObservedLaterDiffersOnlyInObservedAt`). Under `testdata/ctm/defects/`: remove `iftype-subinterface.json`, `iftype-undeclared.json`, `iftype-unimplemented.json`, `link-endpoint-loopback.json`, `mgmt-only-loopback.json` and `parent-missing.json`, and move every other defect to `2`, each still failing by the rule it names alone.

- [ ] T020 `internal/validate` (data-model §2, "Validation"; R-09).
  - **Removed**: the rules `interface.iftype.unimplemented`, `interface.mgmt_only.iftype`, `interface.parent.missing` and `link.endpoint.iftype`, their cases in `rules_test.go` and `defects_test.go`, and their four constants from `internal/findings/finding.go` and `finding_test.go`'s tables (their last users).
  - **Required in the envelope** (`data.required.missing`): `branch`, `observed_at`, `schema_hash`, `scope`, `mapping.reader`, `mapping.model` and `mapping.version`. `contract_version` is no longer required.
  - **The platform**: `platform.package` must be non-empty and in the registry by `psp.Registry.LookupID`; otherwise `platform.unsupported`, naming the package and the registry's ids.
  - **Unchanged**: names unique, links with two ends on distinct devices each naming an interface of a device in the CTM, and the artifact rules.

- [ ] T021 `internal/compiler` (R-07, R-09; data-model §3).
  - **Lookup**: the device's package by `reg.LookupID(platform.package)`, with `Lookup(nos)` gone from product code (grep `internal/` and `cmd/` outside tests).
  - **The survey**: `SurveyDevice` keeps two arms, the `mgmt_only` arm (a second one omitted as `omit.mgmt.extra`) and the data rules. The loopback arm, the `default` arm and `DeviceSurvey.Err` go.
  - **The manifest**: `MappingRow` loses `Iftype`. `Provenance{Branch, At, SchemaHash, Scope, Mapping}` is filled from the envelope. `Fidelity.Read []ctm.FidelityRow` is the envelope's list copied verbatim, `[]` never `null`. `BundleVersion = "5"`.
  - **Unchanged**: the breakout rule, sharing, collisions and `ArtifactNames`.
  - **Tests**: `TestEveryInterfaceIsAPort` (a CTM whose every non-management interface becomes a port, cabled when linked and configured-not-cabled otherwise); the survey tests without the loopback arm; `TestManifestCopiesTheFidelityList` (a CTM with an invented row, whose text appears nowhere in `internal/compiler`, reaches `fidelity.read` unchanged; grep the package's non-test files for each of [contracts/mapping.md](contracts/mapping.md) §5's reason texts and find none); `TestCompilerNamesNoPlatform` and `TestCompilerIsPure` hold; `refusal_parity_test.go` keeps validation's and the compiler's wording alike. Fix `mapping_test.go`, `eos_test.go`, `fidelity_test.go`, `artifact_names_test.go` and `refusal_parity_test.go` where they name the removed constants. Run the golden tests only after T024.

- [ ] T022 Manifest `5` ([contracts/formats.md](contracts/formats.md) "Bundle manifest 5"). Copy the current `contracts/manifest.schema.json` unchanged to `internal/bundle/testdata/contracts/017-dcim-reader/manifest.schema.json` (the frozen `4`). Then move `contracts/manifest.schema.json` to `$id …/contracts/manifest/v5` and `bundle_version` `"5"`:
  - `provenance{branch, at?, schema_hash, scope, mapping{reader, model, version}}`, with `contract_version` gone;
  - `mapping[]` rows without `iftype`;
  - `fidelity.read`, the CTM's fidelity row shape, required.

  In `internal/bundle/verify.go`, accept `5` alone. A `4` is refused as `bundle.version.unsupported`, naming both. Test it in `verify_test.go` with a `4` manifest that is valid against the frozen copy. `internal/compiler/contract_test.go`'s manifest tests run against the new schema.

- [ ] T023 Bridge the old reader over CTM `2`, for two runs (this file's first ordering). Change the least code that keeps `internal/intent`, `internal/stage`, `internal/server` and `internal/cli` compiling, and their tier-1 tests green and truthful:
  - `internal/intent/project.go` stops writing the removed fields, and skips the interfaces the generics type as loopback or subinterface, since CTM `2` has none.
  - `platform.package` is the package the registry finds for the generics' platform `nos`.
  - The envelope's `scope` is `tag:` + `Config.Scope`, and its `mapping` is `{reader: "infrahub-generics", model: "fylgja-generics", version: "0.2"}`, which is what it reads. Its `fidelity` is `[]`.
  - `stage.CheckContract` stays (T042 removes it).
  - Mark the bridge with a comment naming T039. Tests that pin a read's CTM, manifest, record or bundle id move with T019's fixtures and T024's ids.

- [ ] T024 Re-baseline the goldens (FR-032; R-07): after T017–T023, run `go test ./internal/compiler -update`. Review the diff: every manifest's provenance, mapping rows and `fidelity.read`; every bootstrap that lost `lo0`; every artifact. Update every test that pins one of the three old ids (`23f86a26…`, `5773b6bb…`, `391bcb96…`; grep `*.go` and `scripts/`) to the new ids. Commit T017–T023 first, then the goldens and the ids alone, in a commit of their own (`test(compiler): re-baseline the goldens for CTM 2 and manifest 5`), whose body names the three new ids. Write the three new ids in this task's note; `CLAUDE.md` takes them at T071. The loop stops here for the golden diff's review.

- [ ] T025 `twin.json` `8` ([contracts/formats.md](contracts/formats.md) "`twin.json` 8").
  - **Freeze**: copy the current `contracts/twin.schema.json` unchanged to `internal/lab/testdata/contracts/015-proposed-change-rehearsal/twin.schema.json`, the frozen `7`.
  - **The schema**: `contracts/twin.schema.json` moves to `$id …/contracts/twin/v8`, with `twin_version` `"8"` and `provenance` shaped as the manifest's.
  - **The types**: `internal/lab/wire/types.go`'s `Provenance` mirrors `compiler.Provenance` (`Scope`, `Mapping`; no `ContractVersion`), and `internal/lab/twin.go`'s `TwinVersion` becomes `"8"`. A `7` record decodes with no scope.
  - **Tests in `internal/lab/twin_test.go`**: `TestRecord8` (a create's record names its scope and mapping, valid against the contract) and `TestRecord7ReadsWithNoScope` (against the frozen copy). Rename the `…Version7…` tests to `…Version8…`, and make the tests that rewrite a record as an older worker wrote it drop `scope` and `mapping`.
  - **The script**: set `scripts/e2e.sh`'s expected record version to `8`, so that `TestE2EScriptExpectsTheRecordsVersion` passes. The rest of the script is T054's.
  - **The count**: set `frozenContractCopies` in `internal/findings/frozen_contracts_test.go` to the number its glob finds after T017, T022 and this task each add one (30 → 33).

- [ ] T026 The record's provenance in the documents ([contracts/formats.md](contracts/formats.md) "The findings blocks"; R-07).
  - **Types**: `findings.ShowRecord` carries `Scope` and `Mapping` in place of `ContractVersion` (`internal/findings/render.go`), the one document type that carries it. The verify document's `twin` block and the step's two sides name the bundle and the stage, never the record's provenance, and are unchanged; the scope of a step's or a verify's read is the document's `subject.scope`.
  - **Schemas**: `contracts/show.schema.json` moves with it; `verify.schema.json` and `step.schema.json` hold no `contract_version` and do not move.
  - **`twin show`**: the record line reads `record: branch b at …, bundle_id …, schema …, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9`, and for a `7` record `…, scope unknown (record 7)` (built in `internal/server/show.go` and wherever the text line is rendered).
  - **`twin step`** refuses a `7` record as `step.twin.unsteppable`, naming the version (`the twin was created from a record version this build no longer reads (twin.json 7); fylgja twin destroy clears it`), as it refuses a `5` (`internal/server/step.go`).
  - **Other commands on a `7` record**: `twin destroy` clears it, and `twin rehearse` still reclaims one that names a dead rehearsal.
  - **Tests**: `internal/cli/show_test.go` (both lines); `internal/server/step_test.go` (the `7` refusal); the frozen M-era contracts still accept a document without `scope`.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`; the
goldens' commit reviewed.

---

## Phase 6: User Story 6, part 1 — the schema directory, test support, the fixture tool, and the typed client (Priority: P3)

**Goal**: `schema/dcim/` vendored byte for byte, embedded and tested; the generics and the
reference schema gone; test support and the fixture tool writing the library's kinds;
`-prepare-main`'s gate; the typed client generated from a branch that holds the library.

**Independent Test**: `TestVendoredLibraryIsThePinnedCommit` passes; `go vet -tags
contract,fixture,e2e ./...` compiles every tagged file; `go generate ./... && git diff
--exit-code` holds after T033's commit.

- [ ] T027 [P] [US6] Vendor the library (R-12; FR-035). In a new empty directory under the scratchpad, fetch `opsmill/schema-library` at `26336e9026dff1907f2c58e81dd6ae7b5c3f763e` (a shallow clone, or `raw.githubusercontent.com/opsmill/schema-library/<sha>/<path>`). Copy byte for byte to `schema/dcim/`: `base/dcim.yml` → `dcim.yml`, `base/ipam.yml` → `ipam.yml`, `base/location.yml` → `location.yml`, `base/organization.yml` → `organization.yml`, `extensions/cable/cable.yml` → `cable.yml`, `extensions/location_minimal/location_minimal.yml` → `location_minimal.yml`, and `LICENSE.txt`. Check each SHA-256 against research §1.2's prefixes (`81df2eb8…`, `6d31dc03…`, `afef7a77…`, `082e8536…`, `3196073c…`, `cf148227…`, `71d4aed1…`), and stop if any differs. Never format them. Write `schema/dcim/README.md`: the repository and the full commit, a table of each file's library path, vendored name and full SHA-256, the Apache 2.0 licence, that `-prepare-main` loads them in one request on an empty `main` alone (R-13), and that they are never reformatted.

- [ ] T028 [US6] After T002 and T027. In `embed.go`, embed `schema/dcim/*.yml` beside `schema/*.yaml`. Add `TestVendoredLibraryIsThePinnedCommit` in `embed_test.go`: each embedded file's SHA-256 equals the README's table, and the README names `26336e9026dff1907f2c58e81dd6ae7b5c3f763e`. Remove `schema/fylgja-generics.yaml` and `schema/reference.yaml`; `schema/fylgja-stage.yaml` stays. In `internal/testsupport/infrahub.go`, `LoadSchema` loads `schema/dcim/*.yml` in one request, then `schema/*.yaml` (the stage kind) in a second, and waits until `DcimDeviceCreate` and `FylgjaStageCreate` are mutations (data-model §11). `-schema-only` on a throwaway branch loads both.

- [ ] T029 [US6] Load the `infrahub:infrahub-managing-objects` skill and read its SKILL.md before writing the seed, applying it where `CLAUDE.md` does not decide otherwise. Then rewrite `internal/testsupport/seed.go` in the library's kinds, as R-15 and data-model §12 give them:
  - **The objects**: `BuiltinTag fylgja`; `OrganizationManufacturer Nokia`; `DcimPlatform SR Linux` (manufacturer Nokia); `LocationRegion Lab region` → `LocationCountry Lab country` → `LocationMetro Lab metro` → `LocationSite lab`.
  - **The devices**: `n1`, `n2` and `n3`, each with `status active`, `location lab`, `platform SR Linux`, `tags [fylgja]` and `description` the marker. Each has the `InterfacePhysical`s `ethernet-1/1`, `ethernet-1/2` and `mgmt0` (`role management`), and no loopback.
  - **The cables**: three `DcimCable`s, each with `connected_endpoints` its two ports and `label` the link's canonical id. Then the group join and the generate, as today.
  - **The mixed seed**: it adds `Arista` and `EOS`, and the devices `s1`, `e1` and `e2` with their ports as data-model §12's table gives them, and three cables.
  - **The marker**: `MarkerDescription(branch)` = `FYLGJA-MARKER-<suffix>` by today's suffix rule. `MarkerPrefix` stays `FYLGJA-MARKER`.
  - **The helpers**: `EnsureTag`, `EnsureManufacturer`, `EnsurePlatform`, `EnsureSite` and `TagDevices`. `SeedThreeNode`'s idempotence reads `DcimDevice { count }`.
  - **The names**: keep exported names and signatures where the meaning holds, so every `contract`-tagged caller compiles. A renamed one moves at every caller in this task.

- [ ] T030 [US6] The rest of test support in the library's kinds (R-15).
  - **`internal/testsupport/baseline.go`**: `SeedMain` and `ClearMain` write and clear the baseline (the tag, the manufacturer, the platform, the four locations, the three devices, their ports and cables, and the artifacts). Each refuses a `main` that holds any of those, as it refuses one holding the baseline today.
  - **The change helpers**: the add-link change (`ethernet-1/3` on n1 and n3, with their cable); the fourth node (n4 with `mgmt0` and `ethernet-1/1`, cabled to the peer's new `ethernet-1/3`); the mixed link (`s1:ethernet-1/3`, `e1:Ethernet3` and their cable); disable-port (`status: disabled`); and add-interface (an `InterfacePhysical`, uncabled).
  - **New**: `SetDeviceDescription` and `SetDeviceSerial`. `SetRole` and `SetSite` go.
  - **`proposed.go`**'s branch guards are unchanged.
  - **Gate**: `go vet -tags contract,fixture,e2e ./...` compiles every tagged file; tests whose assertions name the generics' kinds are rewritten at T044 and T051.

- [ ] T031 [US6] `cmd/fylgja-fixture/main.go` (FR-036–FR-038; R-13, R-15).
  - **Flags**: `-set-description <v>` sets every device's description on a throwaway branch, the artifact-only change, and replaces `-set-role` and `-set-site`. `-add-link`, `-add-fourth-node`, `-add-mixed-link`, `-disable-port`, `-add-interface`, `-seed-main` and `-clear-main` call T029's and T030's helpers. Each flag's help text names the library's kinds.
  - **`-prepare-main`'s gate**: before any write, it reads `GET /api/schema?branch=main` and lists which of the library's kinds `main` holds: every node and generic the six embedded files define, computed from the embedded YAML rather than a hand list.
  - None held: it loads the six files in one request, then the stage kind, the group and the registration as today, and prints `schema library loaded on main (6 files, opsmill/schema-library@26336e9)`.
  - Any held: it loads nothing and refuses with exit 1, before the group and the registration, with R-13's sentence: `main holds <n> of the schema library's kinds (<sorted names>): -prepare-main is the development host's and CI's tool, which loads the library on an empty main alone; a main that already holds the library is yours, and fylgja schema check says whether it is the one the reader reads`.

- [ ] T032 [US6] `scripts/bring-up.sh`: the part that runs `-prepare-main` reads its exit 1 with R-13's sentence as `present`, and reports `main present (the library, the stage kind, the group, the repository)`. Any other failure stays a refusal. Every check of `main` or the fixture that names the generics' kinds (`/usr/bin/grep -n 'FylgjaDevice\|NetworkDevice\|FylgjaContract' scripts/bring-up.sh`) moves to the library's kinds. `shellcheck scripts/bring-up.sh` is clean. Write in this task's note how CI's runner path reads: fresh `main`, the library loaded, the merged template imported.

- [ ] T033 [US6] The interim SDL and the typed client (R-14 step 5's interim). After T002 and T028. With `local/.env` loaded:
  - Run `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-017-sdl -schema-only`, then `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-017-sdl -sdl schema/infrahub.graphql`, keeping the file's header by hand as `make sdl`'s note says.
  - Capture `GET /api/schema?branch=fylgja-test-017-sdl`, trimmed with `jq` to the nodes `DcimDevice`, `DcimPlatform`, `OrganizationManufacturer`, `InterfacePhysical`, `InterfaceVirtual` and `DcimCable`, the generics `DcimGenericDevice`, `DcimInterface`, `DcimEndpoint`, `DcimConnector` and `CoreArtifactTarget`, and the top-level hash, into `internal/intent/testdata/schema-26336e9.json`. It is T036's fixture. Check it holds no token.
  - Dry-run `infrahub/queries/device_config.gql` against the branch (the skill's `deployment-gql-dry-run` rule), with `device: "none"`: no GraphQL error. Record it in research §5.2.
  - Delete the branch (`-branch fylgja-test-017-sdl -delete`).
  - Run `make generate`. The SDL carries the generics (from `main`) and the library both, so the old and the new operations both generate. Commit, then `go generate ./... && git diff --exit-code` is clean.

- [ ] T034 [US6] Redraw for the schema and the template (`CLAUDE.md`: a changed component is redrawn in the same change). In `docs/c4/workspace.dsl`, the schema is the vendored library and the stage kind, and the artifacts repository renders from the library's kinds. Redraw `docs/diagrams/schema.md` from the six files' kinds the mapping reads (`DcimDevice`, `DcimPlatform`, `OrganizationManufacturer`, `InterfacePhysical`, `DcimCable`, the four generics), with `BuiltinTag` as the scope's tag and `FylgjaStage` with its proposed change, and its prose rewritten. Then run `make diagrams`; a second run changes nothing.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`,
`go generate ./... && git diff --exit-code`.

---

## Phase 7: User Story 3 — "Is my DCIM the one Fylgja reads?" (Priority: P2)

**Goal**: conformance as a per-kind, per-field table against `GET /api/schema`, every
finding naming the commit, in one pass; `schema check` reports it (FR-011–FR-013).

**Independent Test**: against `internal/intent/testdata/schema-26336e9.json`, conformance
passes; with a kind, a field, a choice or an implementer removed or changed, it fails
with one finding each, every one naming `26336e9`, in one pass; extra kinds and fields
are never reported.

- [ ] T035 [US3] After T003 and T004. Create `internal/intent/mapping.go` (data-model §5): `KindTable{Kind, Attributes []AttributeWant{Name, Kind, Required bool, Choices []string}, Relationships []RelationshipWant{Name, Peer, Kind, Cardinality, Required bool}}`, `UsedByWant{Generic, Implementer}`, `LibraryTables` and `LibraryUsedBy`, holding exactly [contracts/mapping.md](contracts/mapping.md) §3's table:
  - `DcimDevice`: `name` Text, required; `tags` → `BuiltinTag`, Attribute, many, optional; `platform` → `DcimPlatform`, Attribute, one, optional; `interfaces` → `DcimInterface`, Component, many, optional; `artifacts` → `CoreArtifact`, Generic, many, optional.
  - `DcimPlatform`: `name` Text, required; `manufacturer` → `OrganizationManufacturer`, Attribute, one, optional.
  - `OrganizationManufacturer`: `name` Text, required.
  - `InterfacePhysical`: `name` Text, required; `role` Dropdown, optional, choices ⊇ {`management`}; `status` Dropdown, optional, choices ⊇ {`disabled`}; `device` → `DcimGenericDevice`, Parent, one, required; `connector` → `DcimConnector`, Attribute, one, optional.
  - `DcimCable`: `connected_endpoints` → `DcimEndpoint`, Attribute, many, optional.
  - `used_by`: `DcimGenericDevice` ⊇ {`DcimDevice`}, `DcimInterface` ⊇ {`InterfacePhysical`}, `DcimEndpoint` ⊇ {`InterfacePhysical`}, `DcimConnector` ⊇ {`DcimCable`}.

  Also add `LibraryModel = ctm.ModelSchemaLibrary` and `LibraryVersion = ctm.ModelVersion`. The package doc comment says this file is the one place that knows the library's kinds.

- [ ] T036 [US3] Conformance (R-02; data-model §5).
  - **`SchemaInfo`** (`internal/intent/schemainfo.go`) gains `Nodes map[string]NodeSchema`, each with `Attributes map[string]AttributeSchema{Kind, Optional, Choices}` and `Relationships map[string]RelationshipSchema{Peer, Kind, Cardinality, Optional}` as the endpoint reports them (inherited members merged in), and keeps `Hash` and `UsedBy`.
  - **`CheckConformance`** (`conformance.go`) walks `LibraryTables` and `LibraryUsedBy` and files `schema.kind.missing` (object the kind), `schema.field.missing` (`<kind>.<field>`), `schema.field.mismatch` (`<kind>.<field>`; the property that differs, expected and found, such as `kind Text, found Number`, `cardinality one, found many`, `peer DcimPlatform, found NetPlatform`, or `optional false, found true`), `schema.choice.missing` (`<kind>.<field>`, the choice) and `schema.used_by.missing` (the generic, the implementer). Every message ends `as opsmill/schema-library@26336e9 has it`; every finding comes in one pass; nothing beyond the table is reported.
  - **`optional`** is compared as the endpoint reports it: a required member must read `optional: false`, and an optional one may read either.
  - **The results**: `Conformance{SchemaHash, Model, Version, Kinds []findings.KindFields}`; `findings.Verified{Model, Version, Kinds, Stages}` and `KindFields{Kind string; Fields []string}` in `internal/findings/render.go`, with `Verified()` in `summary.go`.
  - **Removed**: `schema.generic.unimplemented` and `schema.artifact_target.missing`, with their constants (their last users), and the generics-only code in `conformance.go`. The old `Fetch` keeps working off the new `Conformance`'s `SchemaHash` until T039.
  - **Tests** in `internal/intent/conformance_test.go`, over `httptest` serving `testdata/schema-26336e9.json` and mutations of it: a pass; `DcimCable` removed; `InterfacePhysical.role` removed; `DcimPlatform.name` as Number; `DcimDevice.platform` many and peered to `NetPlatform`; `DcimDevice.name` optional; `management` removed from `role`'s choices; `InterfacePhysical` removed from `DcimEndpoint.used_by`; all at once, giving every finding in one pass. Plus an extra kind and an extra field on `DcimDevice`, never reported. Each finding names `26336e9`.

- [ ] T037 [US3] `fylgja schema check` (FR-013; R-02, R-17).
  - **Success**: in `internal/server/schema.go`, the line is `conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, OrganizationManufacturer, InterfacePhysical, DcimCable`, then the stages line as today.
  - **`--json`**: `verified` is `{model, version, kinds: [{kind, fields: [...]}], stages}`, and `contracts/findings.schema.json`'s `verified` definition moves to it (`contract_version` and `generics` go).
  - **The harness's fake Infrahub** (`internal/cli/infrahub_test.go`) serves the trimmed schema document of T033 at `GET /api/schema`, beside its generics GraphQL answers, until T043.
  - **Tests**: `internal/server/schema_test.go` and `internal/cli/schema_test.go`: the success line and block valid against the schema, and a failing branch's findings, all in one document.

**Checkpoint**: `make test`, `make lint`.

---

## Phase 8: User Stories 1 and 2 — the read, its completeness and its omissions (Priority: P1) 🎯 MVP

**Goal**: two queries read the scope: devices by tag, ports by device ids, each cable
through its port's connector. Each device's package is found by its pair. Inside the
scope the read is strict; a cable at the scope's edge is omitted and recorded. The
envelope carries the scope, the mapping and the fidelity list (FR-001–FR-011, FR-014,
FR-015, FR-019, FR-029).

**Independent Test**: against an `httptest` Infrahub answering research §1.6's shapes, the
three-node read equals `testdata/ctm/three-node.json` except for the envelope. A
three-ended, a one-ended, an outside and a foreign-typed cable are each omitted with their
rule, reason and row. A device with no platform, one with an orphan platform and one on
`nokia` / `SR-Linux` are refused in one pass with no CTM. `tag:nothing` is `scope.empty`.

- [ ] T038 [US1] In `internal/intent/queries.graphql`, replace `ContractVersion`, the fragments `PlatformFields` and `InterfaceFields`, and the operations `Devices` and `Links` with [contracts/mapping.md](contracts/mapping.md) §2's two operations. Keep `ArtifactFields`.
  - `Devices($tag: String!, $limit: Int!, $offset: Int!)` is `DcimDevice(tags__name__value: $tag, limit, offset)`, selecting `id`, `name { value }`, `platform { node { name { value } manufacturer { node { name { value } } } } }` and `...ArtifactFields`. It selects no `interfaces`.
  - `Ports($devices: [ID], $limit: Int!, $offset: Int!)` is `InterfacePhysical(device__ids: $devices, limit, offset)`, selecting `id`, `name { value }`, `role { value }`, `status { value }`, `device { node { id } }` and `connector { node { id ... on DcimCable { label { value } } connected_endpoints { count edges { node { __typename id ... on InterfacePhysical { name { value } device { node { id } } } } } } } }`.
  - The stamps and the stage reader's operations are unchanged (T047).
  - Run `make generate`.

- [ ] T039 [US1] [US2] The read (R-01, R-05, R-06; data-model §6), in `internal/intent/project.go` and a new `internal/intent/cable.go`. This replaces T023's bridge.
  - **`Fetch`** runs `Devices` with `Config.Scope`'s tag, paged by 100, every page at the read's `at` when one was given. Then it runs `Ports` once per page of 100 device ids, projects, judges the cables, writes the fidelity list, fetches the artifacts as today, relinks and normalizes.
  - **A port** is one per `InterfacePhysical`, by `name`. `mgmt_only` is `role == management`; `enabled` is `false` only when `status == disabled` (`null` and every other value is `true`).
  - **A cable** is judged once, by its id (`cableJudgement{id, label, ends []end{deviceID, deviceName, port, kind}}`), with the first reason that applies, in R-05's order:
    - `omit.cable.ends` when `count != 2`;
    - `omit.cable.endpoint` when an end's `__typename` is not `InterfacePhysical`;
    - `omit.cable.outside_scope` when an end's device id is not among the devices read.

    Each omission is an `info` finding beside the read: its object is the cable's `label`, or its id when it has none, and its message gives the reason text of [contracts/mapping.md](contracts/mapping.md) §4 (`other than two ends (<n>)`, `an end not on a physical port (<kind>)`, `an end outside the scope (<device>:<port>)`) and names every known end as `<device>:<port>`. Each is also a fidelity row `{omitted, <object>, DcimCable, <reason>}`. Any other cable is a link with today's canonical id, both ports `link`ed.
  - **The envelope** gets `scope` (`tag:<name>`), `mapping` (the three constants) and `fidelity` (the three fixed rows of T019 plus one per omitted cable, sorted).

- [ ] T040 [US2] Completeness inside the scope (R-03; FR-014, FR-015), in `internal/intent/project.go` or a new `completeness.go`. Before any artifact is fetched, in one pass and with no CTM on any of them:
  - `scope.empty` (object the scope, the message naming the scope and the branch) when `Devices` answered 0.
  - `platform.missing` (object the device) for no platform, or a platform with no manufacturer. The message names what the device carries: `no platform`, or `platform "Orphan OS" with no manufacturer`.
  - `platform.unmatched` (object the device) when `reg.Match` finds nothing. The message is `manufacturer "nokia", platform "SR-Linux"; the packages match: nokia_srlinux [Nokia / SR Linux], arista_eos [Arista / EOS]`, every package and pair listed in a stable order.

  A device refused for its platform is not also refused for its artifact. The artifact rules are unchanged (FR-008).

- [ ] T041 [US1] The read's report (R-17). `Counts.CablesOmitted` and `DevicesByPackage` reading `platform.package` live in `internal/intent/summary.go`. `intent read`'s summary line is `wrote <file>: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports; 1 cable omitted (branch b, scope tag:fylgja, schema 908871c3…)`, the omitted count only when non-zero, with a stage's `stage b/seeded: …` first as today (`internal/server/read.go` and where the line is rendered).

- [ ] T042 [US1] `stage.Read` without the contract (`internal/stage/stage.go`). Remove `CheckContract`, and with it `contract.version.mismatch` and its constant (its last user). `twin compile` given a CTM of another version files `ctm.version.unsupported` (object the CTM file, exit 1, no step), naming both versions (`internal/server/compile.go`). Test it in `internal/server` or `internal/cli` with `testdata/ctm/defects/version-1.json`.

- [ ] T043 [US1] [US2] The read's tier-1 tests (R-18; quickstart §1).
  - **The fake**: rewrite the harness's fake Infrahub (`internal/cli/infrahub_test.go`) to answer `Devices` and `Ports` in research §1.6's shapes for the three-node fixture, whose read equals `testdata/ctm/three-node.json` except for the envelope. Drop its generics answers (the stamps' too, if T047's run has not yet moved them: keep only what the old stamps operations still read).
  - **`internal/intent/project_test.go` and `cable_test.go`**, against an `httptest` Infrahub:
    - the three-node read, with the request's variables asserted: `tags__name__value` is `fylgja`, no status filter, and `Ports`' `device__ids` are the devices read;
    - an untagged console server and a tagged device's `InterfaceVirtual`s and addresses never requested or read (US1 scenario 3);
    - a three-ended, a one-ended, an outside and a foreign-typed cable, each omitted with its rule, reason and row; one cable reached from both ends judged once;
    - a management-to-management cable reaching the CTM (FR-007);
    - a device with no physical interface;
    - a `disabled` port;
    - `n2` with `status maintenance`, read;
    - no platform, `Orphan OS` and `nokia` / `SR-Linux`, refused in one pass with no CTM;
    - `tag:nothing`, refused `scope.empty`.
  - **Moved**: every `internal/intent`, `internal/stage`, `internal/server` and `internal/cli` test that read through the old shapes.

- [ ] T044 [US1] [US2] [US3] The tier-2 tests of the read (quickstart §7; R-18), written against the re-seeded fixtures and throwaway `fylgja-test-*` branches, each deleted by the test that made it. They are run at T062; here they must compile (`go vet -tags contract ./...`).
  - `internal/intent/read_contract_test.go`:
    - `TestFixtureReadsToTheThreeNodeCTM`: `fylgja-fixture` reads to `testdata/ctm/three-node.json`'s content except for the envelope; the envelope's scope, mapping and three rows are asserted.
    - `TestCablesTheReadCannotPlace`: a seeded branch gets an untagged `cs1` with a port, a cable `n1:ethernet-1/3`↔`cs1:port1`, and a three-ended cable. Each is a finding and a row; `cs1` is absent.
    - `TestPlatformsTheReadRefuses`: `n1` on `nokia` / `SR-Linux`, and `n2` with no platform, give one pass and no CTM.
    - `TestScopeSelectsNothing`: `tag:nothing`.
  - `internal/intent/conformance_contract_test.go`: `TestSchemaCheckNamesAMissingKind`. A throwaway branch loads `internal/intent/testdata/dcim-cable-absent.yaml` (a `state: absent` document for `DcimCable`, about 40 s); `CheckConformance` and the read then refuse with `schema.kind.missing DcimCable`.
  - `internal/cli/schema_contract_test.go`: `TestSchemaCheckPassesOnBothFixtures`, through the harness's server. The success line names the commit on `fylgja-fixture` and on a `-mixed` throwaway branch.
  - `internal/intent/defects_contract_test.go`: rewrite it to the library's defects, or remove it if T036's and this task's cases cover each.
  - `internal/stage/artifact_contract_test.go`:
    - `TestArtifactOnASeededBranch`: `SetDeviceDescription` moves the id; `SetDeviceSerial` regenerates identical bytes and moves nothing; a device outside `fylgja-devices` is `artifact.missing` (US2 scenario 7).
  - `mixed_contract_test.go`: `TestMixedSeedReads`.
  - `reproducibility_contract_test.go`: `TestPinnedReadReproducesItsBundle`, a pinned read filtering by tag.
  - `following_contract_test.go`: `TestFollowingDetection`.

- [ ] T045 [US1] Redraw the intent component in `docs/c4/workspace.dsl`: it reads the library's DCIM by the mapping in two queries, and conformance is a table naming the commit. Then run `make diagrams`; a second run changes nothing.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`. The
MVP's reader is complete in tier 1.

---

## Phase 9: User Story 1, part 3 — the step's and the follow's reads under the record's scope (Priority: P1)

**Goal**: `twin step` and the following twin read under the scope the twin records, never
the server's default (FR-020; US1 scenario 7); the headings name the scope (R-17).

**Independent Test**: through the harness, with the server's default `tag:other` and a
record of `tag:fylgja`, `twin step`'s target read sends `tags__name__value: fylgja`.

- [ ] T046 [US1] `twin step` (`internal/server/step.go`, `internal/stages/target.go`) takes the scope from the record's `provenance.scope` for the target's resolution, its staleness and its read. The following twin's reads take `ProvisionInput.Scope` through `ReconcileInput` and `ReadIntentInput` (`internal/provision/`), set at create from the request's scope. The headings of `stage plan` and `twin rehearse` end `, scope tag:fylgja` (where each is built: `internal/stages/blocks.go`, `internal/server/rehearse.go`), and the rehearsal's document carries `subject.scope`. The rehearsal's markdown report (`internal/rehearsal/markdown.go`, `parts`) names the scope in its heading after the branch (`… on branch b → main, scope tag:fylgja`), kept by `fit` as the heading is, so the comment `fylgja-twin` posts names the scope read (US5 scenario 4). Tests in `internal/rehearsal/markdown_test.go`: the heading carries it in the full and the shortened forms; `TestMarkdown`'s expected text moves. Tests:
  - the harness case above, and its follow equivalent in `internal/provision/workflow_reconcile_test.go` (the scope reaches the read activity);
  - `stage plan --scope tag:x` sends `x` on every stage's read (US5 scenario 5);
  - the nine histories replay.

**Checkpoint**: `make test`, `make lint`.

---

## Phase 10: User Story 5 — Stages and rehearsals over the new model (Priority: P2)

**Goal**: a device's intent stamp is the latest `node_metadata.updated_at` among
everything it owns or reaches by a cable; intent events are any write on those nodes but
Infrahub's churn; the branch point's `scope.empty` is passed over where 0.2's
`contract.node.missing` was (FR-015, FR-021–FR-024).

**Independent Test**: over faked answers, a device's stamp moves with its virtual
interface's, platform's, manufacturer's and cable's; a `member_of_groups` update counts
for nothing; a re-ended cable's event reaches its former port; an untagged device's write
makes no tagged device stale.

- [ ] T047 [US5] The stamps (R-10; data-model §7). In `internal/intent/queries.graphql`, replace `IntentStamps` and the fragment `PlatformStamps` with two operations shaped like T038's, selecting stamps and ids alone:
  - per device: the device edge's `node_metadata { updated_at }`; `platform { node_metadata { updated_at } node { id name { value } manufacturer { node_metadata { updated_at } node { id name { value } } } } }`; `interfaces { edges { node_metadata { updated_at } node { id } } }` (both kinds); and `...ArtifactStamps`;
  - per physical port: `connector { node_metadata { updated_at } node { id } }`.

  Then run `make generate`. In `internal/intent/stamps.go`:
  - `Stamps(ctx, scope)` reads under the scope's tag.
  - `DeviceStamps{Match psp.Match, IDs []string, Intent string, Artifacts map[string]string}`. `IDs` holds the device, every interface, the platform, the manufacturer and every cable; `Intent` is the latest stamp among them.
  - `Stamps.Latest` folds every device's and every artifact's stamp, as today.

  Tests in `stamps_test.go`, over faked `node_metadata` answers: each of the five sources moving the device's stamp alone; a cable shared by two devices moving both; a null stamp skipped.

- [ ] T048 [US5] The events (R-10; research §1.8), in `internal/intent/events.go`.
  - `intentKinds` maps the branch schema's `used_by` of `DcimGenericDevice`, `DcimInterface` and `DcimConnector`, plus `DcimPlatform` and `OrganizationManufacturer`, to "intent's". `ctm.DeviceGeneric` and its kin leave this file.
  - `changesIntent` is true for a creation or a deletion, any attribute, or any relationship not in `churnRelationships = {member_of_groups, subscriber_of_groups, artifacts, profiles, object_template}`.
  - An event with no primary node is skipped. `Event.Names` is unchanged.
  - Tests in `events_test.go`: a `member_of_groups` update is ignored; a cable's `connected_endpoints` update names its former port and counts for that port's device; a port's `connector` update counts; an `infrahub.schema.updated` event with no primary node is skipped; a tag added and removed counts.

- [ ] T049 [US5] The staleness rule (`internal/stages/stale.go`) resolves `DeviceStamps.Match` to the package through `reg.Match`; a device whose pair no package matches is reported as the read would report it. Tests in `internal/stages/stale_test.go`: a device's cable, platform and manufacturer stamps each make its mark stale, and an untagged device's write makes none stale (US5 scenarios 1 and 2). Move the harness's stage tests (`internal/cli/stage_test.go`, `stage_plan_test.go`, `stage_create_test.go`, `twin_step_test.go`) and the fake's stamps answers to the library's shapes.

- [ ] T050 [US5] `scope.empty` at the branch point (R-20; FR-015; US5 scenario 3).
  - The stage resolution (`internal/stages/resolve.go`, or wherever `contract.node.missing` was filed for a branch point) files `scope.empty` at step `resolve`.
  - `passedOver` in `internal/server/rehearse.go` excuses `scope.empty` where it excused `contract.node.missing`.
  - In `infrahub/checks/fylgja_api.py`, `RULE_NODE_MISSING` becomes `RULE_SCOPE_EMPTY = "scope.empty"`, and `branch_point_refusal` and the docstrings follow. The comments in `fylgja_step.py` and `fylgja_twin.py` move too. Run `.venv/bin/python -I -m py_compile infrahub/checks/*.py`.
  - Confirm with `/usr/bin/grep -n scope infrahub/checks/*.py` that no check sends a `scope` (FR-021). A server with no default refuses the check's request `scope.unset`, which the check concludes as failure, as it concludes any refusal it does not excuse.
  - Remove `contract.node.missing`'s constant and every use (`/usr/bin/grep -rn 'contract.node.missing\|RuleContractNodeMissing'` over `*.go`, `*.py` and `*.sh`, but `scripts/e2e.sh`, which is T054's).
  - Move `internal/server/rehearse_test.go`, `internal/provision/workflow_rehearse_test.go`, `internal/rehearsal/*_test.go`, `internal/findings/stages_test.go` and `rehearsal_test.go`, and `internal/cli/twin_rehearse_test.go`.

- [ ] T051 [US5] The tier-2 tests of stages and the checks (quickstart §6, §7; SC-006, SC-009), over the library's kinds. They are run at T062; here they must compile.
  - `internal/stages/stages_contract_test.go`:
    - `TestStagesSeeEveryWriteOfADevice`, new. After a mark on a throwaway branch's draft proposed change: an `InterfaceVirtual` added to `n1`, `n1`'s platform's `description`, the manufacturer's `description`, and the cable on `n1:ethernet-1/1` re-ended. Each makes `stage.artifact.stale n1` (and `n2` for the cable). An edit of an untagged `cs1` makes no mark stale.
    - `TestStagesListAndPlan`'s branch point is refused with `scope.empty` on a `main` holding no tagged device.
    - `TestStageRefusals`'s identical-bytes case uses `SetDeviceSerial` in place of the site edit.
    - `TestStagesSeeARemoval` runs over a cable's delete.
  - `internal/server/rehearse_contract_test.go` and `internal/checks/checks_contract_test.go` keep their assertions, but for the renamed identifier.

- [ ] T052 [US5] The read-only test (`internal/intent/readonly_test.go`; FR-001, SC-002). Replace `TestQueriesNameOnlyGenerics`, `TestQueryRootsAreFylgjaGenerics` and `TestQueryRootExceptionsAreNamed` with:
  - `TestQueryRootsAreTheMappings`: every operation's roots are among `DcimDevice` and `InterfacePhysical`, the mapping's kinds, plus `FylgjaStage`, `CoreProposedChange`, `CoreArtifactValidator`, `Branch` and `InfrahubEvent`, the Infrahub-owned or Fylgja's, each with its reason.
  - `TestFragmentTargetsAreTheMappings`: every `fragment … on` and `... on` target is among `DcimDevice`, `DcimPlatform`, `InterfacePhysical`, `DcimCable`, `CoreArtifactTarget` and `NodeMutatedEvent`.
  - A named entry for `BuiltinTag`, read by the `tags__name__value` filter alone, as the Infrahub-owned read FR-001 names.

  Adding a fifth kind of the operator's model to any operation fails a test. `TestEveryOperationIsAQuery` stays.

- [ ] T053 [US5] Retire what the generics left (FR-016).
  - **Constants**: remove `ctm.ContractVersion`, `ContractKind`, `RequiredGenerics`, `DeviceGeneric` and `ArtifactTargetGeneric`, and every user still left (`internal/cli`, `internal/provision/activities_test.go`, `internal/server/schema.go`).
  - **Operations**: `queries.graphql` names no `Fylgja*` kind but `FylgjaStage`, and no `Network*` kind.
  - **Identifiers**: confirm all eight of R-21's retired ones are gone from `internal/findings` and every test.
  - **Grep**: `/usr/bin/grep -rn 'FylgjaDevice\|FylgjaInterface\|FylgjaPlatform\|FylgjaLink\|FylgjaContract\|NetworkDevice\|iftype\|ContractVersion\|contract_version' --include='*.go' .` finds only `internal/intent/generated.go` (the interim SDL's types, gone at T060) and the frozen copies under `testdata/`.
  - **Gates**: `make test` uncached, under 45 s, its time noted; `make lint`; `go vet -tags contract,fixture,e2e ./...`.

**Checkpoint**: the code of the feature is complete in tier 1. Every tagged test compiles.

---

## Phase 11: User Story 6, part 2 — the install migrated, the fixtures re-seeded, the tiers (Priority: P3)

**Goal**: the development host's `main` migrated in the documented order (R-14), the
template imported, the fixture re-seeded, the client regenerated from the migrated `main`,
and every tier green over the library's kinds (SC-001, SC-003–SC-006, SC-009).

**Independent Test**: after the migration, `main` lists the library's kinds and the stage
kind and none of the generics; `-prepare-main` run again refuses naming the kinds found;
the fixture reads to its CTM; tier 2 is green; the nine tier-3 cases pass with the marker
in `description`.

- [ ] T054 [US6] `scripts/e2e.sh` (R-18 tier 3; FR-038).
  - The marker is the device's `description`, so the comments around `MARKER='FYLGJA-MARKER'` (the "role comment" lines) say the header. Every `-set-role` and `-set-site` becomes `-set-description`.
  - Every assertion that names the generics' kinds or `contract.node.missing` moves to the library's kinds and `scope.empty`.
  - Case 1 asserts `twin show`'s `scope tag:fylgja` and `read by infrahub-dcim from opsmill/schema-library@26336e9`. Case 5 passes `--scope tag:fylgja`.
  - `shellcheck scripts/e2e.sh` is clean. Check the changed greps offline against the recorded `local/e2e-*.outputs`, as the memory note on tier 3's outputs describes.

- [ ] T055 [operator] [US6] Before the host moves: add `FYLGJA_DEFAULT_SCOPE="tag:fylgja"` to `local/.env` (the operator's file, which the bring-up script keeps byte for byte; values there are quoted), and give the go-ahead for `main`'s migration (T056), this feature's one lasting write to `main`. Say whether a live session runs it or the operator does. Precondition: T002 done, and no tier, loop or twin running against Infrahub.

- [ ] T056 [live] [US6] Migrate `main` (quickstart §2 steps 1–2; research §1.9, R-13, R-14 steps 1–2), with `local/.env` loaded:
  - **The two documents**: `.venv/bin/infrahubctl schema check --branch main specs/017-dcim-reader/migration/1-reference-kinds-absent.yaml`, then `schema load` of the same; then `check` and `load` of `2-generics-absent.yaml`, about 50 s each. Expect `removed:` naming the five, then the four.
  - **Verify**: `GET /api/schema?branch=main` lists `FylgjaStage` alone of the `Fylgja*` and `Network*` kinds, and a new hash. `FylgjaStage` and its `CoreProposedChange` extension are untouched.
  - **The library**: `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` prints `schema library loaded on main (6 files, opsmill/schema-library@26336e9)`, `stage kind present`, `group fylgja-devices present` and `repository fylgja present`. Run it again: it refuses, exit 1, naming the kinds it found (the number found, 21 expected), and writes nothing.
  - **Record** in research §5.3: each output, `main`'s new hash from `/api/schema/summary`, and the timings.

- [ ] T057 [operator] [US6] Merge `017-dcim-reader` into `main` and push `origin`'s `main` (R-14 step 3; FR-040). It is the whole branch, not the template commit alone: the registration follows `ref main`, and CI's contract job on that push brings its own Infrahub up with this tree's fixture tool, seeds the library's kinds and renders through the merged template, so a cherry-pick of the template would go red. `main` then carries code tiers 2 and 3 have not yet proved on this host (T062, T063), and T060 may add a second golden commit that needs a second merge and push; the operator accepts that here or stops. After T054. Read the job's result and record it in this task's note; a failure there is a defect to fix in the phase that owns it, then merged and pushed again.

- [ ] T058 [live] [US6] Import the pushed commit (quickstart §2 step 3). Look up `CoreReadOnlyRepository` `fylgja`'s id, then run `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on `main`. Wait for the import's flow, and about 15 s more for both task workers to fetch it. Check that no `git_repositories_sync` run is stuck `PENDING`. Verify:
  - the registration's `commit` is the pushed head;
  - `CoreGraphQLQuery device_config`'s query names `DcimDevice`;
  - the two check definitions `fylgja-step` and `fylgja-twin` are still registered.

  Record in research §5.4 the owed fact: the rewritten query imports on a `main` that holds the library.

- [ ] T059 [live] [US6] Rebuild (`make build`), then restart the worker and the server from this tree with `CLAUDE.md`'s two start lines, and verify both as `CLAUDE.md` says:
  - `/proc/<pid>/exe` not `(deleted)`;
  - the environment names, `FYLGJA_DEFAULT_SCOPE` among the server's;
  - the server's report naming both listeners, the bridge warning, both packages with their logins set, and `default scope: tag:fylgja`;
  - from inside each task worker, `POST /v1/twin/show` answers `200` with the token and `401` without it.

- [ ] T060 [live] [US6] Re-seed and regenerate (R-14 steps 4–5; FR-037, FR-039).
  - **The fixture**: `make infrahub-clean && make infrahub-seed` prints `three-node fixture seeded on fylgja-fixture, with every artifact rendered and Ready`.
  - **The client**: `make sdl && make generate`, after which `schema/infrahub.graphql` and `internal/intent/generated.go` hold no generic. Commit them (`chore(intent): the SDL and the typed client from the migrated main`), then confirm `go generate ./... && git diff --exit-code`, `make test`, `make lint` and `go vet -tags contract,fixture,e2e ./...`.
  - **The render check**: compare `bin/fylgja intent read --branch fylgja-fixture`'s artifacts with T016's predicted bytes in `testdata/ctm/three-node.json`, and a `-mixed` throwaway branch's read with `mixed.json`.
    - If they differ, take the real bytes into both fixtures and their shuffled copies, re-run `go test ./internal/compiler -update`, and commit the goldens alone, naming the new ids; the loop stops for the review. The operator then merges and pushes `main` again, as T057, before T063, so that CI's `main` and the script agree on the ids.
    - Record in research §5.1 whether the prediction held.

- [ ] T061 [live] [US1] [US2] [US3] [US5] The hand scenarios (quickstart §3–§6), each recorded in research §5.5 with its output. Delete every throwaway branch at the end.
  - **§3, the fixture read**: `schema check`'s line; `intent read`'s line and the `diff` against `three-node.json` reading `same`; the envelope; `twin compile`, with the manifest's provenance and `fidelity.read`. Record the bundle id as the fixture's compiled id.
  - **§4, the scope**: `tag:fylgja`, `tag:nothing`, `fylgja`, `--scope=` and `twin step --scope`. Then a scratch server with no default, on a scratch port and state root, refusing `scope.unset` with no read in its log.
  - **§5, omissions and refusals**: on `fylgja-test-017-hand`, two `info` findings and five rows; then `platform.unmatched n1` and `platform.missing n2` in one pass, with no file written.
  - **§6, stages**: the four stale edits, the untagged edit, and the branch point `refused (scope.empty)`.

- [ ] T062 [live] [US1] [US2] [US3] [US5] [US6] Tier 2 whole (quickstart §7; SC-001, SC-003–SC-006, SC-009), on a host with no twin, the server on the bridge from this tree (T059): `set -a; . local/.env; set +a; make test-contract 2>&1 | tee local/017-contract.out`.
  - Green: every new test of T044 and T051, and every 014 and 015 test.
  - After it: `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and `CoreUserValidator` count 0; `Branch` lists `main` and `fylgja-fixture` alone; `main` holds no tagged device.
  - Record each package's time and the tier's in research §5.6, with the owed facts: `schema.kind.missing`'s wording on a real branch; the pinned read filtering by tag; `BranchRebase` over the library's kinds (`TestStageRefusals`' rebase case).
  - A failure is fixed in the phase that owns the behaviour, with a tier-1 test pinning it where one can.

- [ ] T063 [live] [US6] Tier 3 on a quiet host (quickstart §8; SC-006), after T062 and never beside it. Read `free -m`; check both images, the worker and the server from this tree, and the checks and the template imported (T058).
  - Start `make test-e2e 2>&1 | tee local/017-e2e.out` detached, with its exit status in a file, and wait in foreground calls of under ten minutes.
  - Expected: `E2E-OK`, nine cases, the marker found in no output, record, document, history or log, and case 1's `twin show` naming `scope tag:fylgja`.
  - Then `PLATFORMS=nokia_srlinux make test-e2e` once: `E2E-PARTIAL`.
  - Record both times in research §5.6, and rest the host between the runs.

**Checkpoint**: every tier green over the library's kinds; the host left as the contract
tier leaves it.

---

## Phase 12: Polish & the close

**Purpose**: the records say what is true afterwards (FR-041, FR-042; R-19).

- [ ] T064 [P] `docs/architecture.md` (R-19): §2 (the pipeline's first step), §3 (core objects: the scope), §4.1 rewritten around the mapping, §4.2, §4.3 (wiring derivation: every interface a port), §4.7 (`matches`, `0.7`), §5 (the source of truth row), §6 ("The branch point needs a tagged device on `main`"; "Intent-conformant"), and the open questions. Every hit T003 noted for the old positions is rewritten or cites D-057.

- [ ] T065 [P] `docs/glossary.md` (R-19):
  - **New**: *mapping* (the documented rule, one per reader; the entry also tells it from the envelope's and the provenance's `mapping` block, which names the reader and the model version, and from the manifest's `mapping[]` port rows, as [contracts/formats.md](contracts/formats.md) does), *approximation*, *omission*, *scope*, *schema library*, *package match* and *node stamp*.
  - **Changed**: *CTM*, *fidelity manifest*, *fixture branch*, *fixture tool*, *artifacts template*, *intent* and *mixed twin*.
  - **Retired**, each kept as a "retired at 017" one-liner: *contract version*, *generics*, *graduate, don't gate* and *reference schema*.

- [ ] T066 [P] `docs/development.md`:
  - **The layout**: `schema/`'s line (the vendored library and the stage kind) and `internal/intent`'s (the mapping, two queries).
  - **The fixture tool's paragraph**: `-set-description` in place of `-set-role` and `-set-site`, the flags over the library's kinds, and `-prepare-main`'s gate.
  - **The tiers' rows**: tier 1's read and conformance cases; tier 2's new tests and T062's times.
  - **The migration**, the environment table's `FYLGJA_DEFAULT_SCOPE`, and the Constitution gates' blessed layers (the mapping, D-057, in place of the generics contract, D-002).

- [ ] T067 [P] `docs/verified-facts.md`: research §1 whole and §5, each fact with its Infrahub version and date. Amend the 09-28 line on `_updated_at`: the node type has no stamp, and the `Edged*` wrapper's `node_metadata` does (§1.4).

- [ ] T068 [P] `README.md`'s walk-through: the `contract 0.2` line, and the five `contract.node.missing` lines, which become `scope.empty`; `--scope` where a command names it. `docs/brief.md` lines 51–53. `docs/roadmap.md`: F-011 built, and Release 0.3's next spec named.

- [ ] T069 [P] Rewrite `schema/README.md`:
  - R-12's table and [contracts/mapping.md](contracts/mapping.md) as its mapping section;
  - what `schema check` reports;
  - what a diverged DCIM costs (a reader of its own);
  - the shipped template as a reference transform, to be replaced by the user's own rendering their layer 2 and 3;
  - that a tagged device outside `fylgja-devices` has no artifact and is refused (FR-034), and that a match is exact;
  - the guide to marking a stage, kept.

  `psp/README.md`: Format 0.7, `platform.matches` and its exactness.

- [ ] T070 [P] `contracts/cli.md` and `contracts/api.md`: a section "017: the scope and the DCIM reader" in each, from [contracts/scope-and-commands.md](contracts/scope-and-commands.md) and [contracts/formats.md](contracts/formats.md): the flags, the setting, the argument, the identifiers with their severities, exits and steps, the text lines, CTM `2`, bundle `5`, `twin.json` `8`, PSP `0.7`, and the retired contract version.

- [ ] T071 `CLAUDE.md`, after T060–T063:
  - **Environment**: `main`'s schema (the library and the stage kind) and its new hash beside the old ones; the fixture branch in the library's kinds, its schema hash and its compiled id; the writes to `main` (`-prepare-main`'s gate); `local/.env`'s `FYLGJA_DEFAULT_SCOPE`; the server's report line.
  - **Formats**: CTM `2`, bundle `5`, `twin.json` `8`, PSP `0.7`, the contract retired, the goldens' new ids and the fixture's id.
  - **The verified facts a session acts on**: any that moved.
  - **The reading list's schema sentence**, and the OpsMill skills paragraph's mention of `FylgjaStage` beside the library.
  - **State**: 017 done, under Release 0.3.

- [ ] T072 [P] Re-read `.env.example` and `SECURITY.md` against what runs (T059, T063), and correct any sentence that no longer holds.

- [ ] T073 The closing gates and hygiene (quickstart §1, §9; SC-007, SC-008):
  - **Gates**: `make build`, statically linked; `make test` uncached under 45 s, its time and load average noted; `make lint`; `go vet -tags contract,fixture,e2e ./...`; `go generate ./... && git diff --exit-code`; `make linkcheck` clean; `make diagrams` changing nothing on a second run; `TestVendoredLibraryIsThePinnedCommit` green.
  - **The retired names**: `/usr/bin/grep -rn 'FylgjaDevice\|FylgjaContract\|iftype\|contract_version\|set-role' --include='*.md' --include='*.go' --include='*.json' --include='*.yaml' --include='*.sh' .` finds them only in the decision log, the archives, 014's and 015's records, this feature's records and the frozen copies.
  - **Credentials**: the greps of 015's quickstart over the tree and the tier outputs find nothing.

- [ ] T074 [operator] The operator reads the feature's diff and its records, commits by hand (conventional messages, bodies saying why), and runs `make command-log` once the session is closed.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: T001 first. T002–T005 are the operator's. T002 blocks T028 and every Infrahub write; T003 and T004 block Phase 5 (T017 onward), Phase 6 and Phase 7, since T018, T020 and T028 remove what Constitution 1.3.0's III mandates; T005's answer may move T012–T014 and Phase 11's order.
- **The identifiers (Phase 2)**: after T001. Before every task that files a new rule.
- **US4 (Phase 3)**: after T006. T007 → T008 → T009 → T010. Blocks T021 (`LookupID` on `0.7` packages) and T040 (`reg.Match`).
- **US1, the request's scope (Phase 4)**: after T006. T011 → T012 → T013 → T014; T015 beside T014. Blocks T023 (the bridge records `Config.Scope`).
- **The formats (Phase 5)**: T016 beside Phases 3–4. T017–T024 after Phases 3 and 4, T003, T004 and T016, in one run, in order; T024 last, alone in its commit. T025 → T026 after T024.
- **US6 part 1 (Phase 6)**: T027 any time. T028 after T002 and T027. T029 → T030 → T031 → T032. T033 after T028 and T029. T034 after T028 and T016.
- **US3 (Phase 7)**: after T003, T004 and T033. T035 → T036 → T037.
- **US1 and US2, the read (Phase 8)**: after Phase 7. T038 → T039 → T040 → T041; T042 beside T041; T043 after T039–T042; T044 after T030 and T043; T045 last.
- **US1, the record's scope (Phase 9)**: T046 after T025 and T039.
- **US5 (Phase 10)**: after Phase 8. T047 → T048 → T049 → T050; T051 after T030 and T050; T052 after T047; T053 last.
- **US6 part 2 (Phase 11)**: T054 after T050. T055 after T053 and T054. T056 after T055 and T031. T057 after T054, the operator's push; T058 after T056 and T057. T059 after T058. T060 after T059. T061 after T060. T062 after T061, never beside a twin. T063 after T062, never beside tier 2.
- **Polish (Phase 12)**: after Phase 11. T067 needs §5's records; T071 needs T060–T063's ids and times. T073 after T064–T072. T074 last.

### Within a phase

Pure code is gated in tier 1 before its harness, tier-2 or live proof. A story's test
names the scenario it proves. A defect a test finds is fixed in that phase, in the package
that holds the behaviour, before the checkpoint. A live task's defect gets a tier-1 test
that pins it.

### Parallel opportunities

- Phase 2's T006, Phase 5's T016 and Phase 6's T027 can run beside Phases 3 and 4.
- Phase 6: T034 beside T029–T033 once T028 is in.
- Phase 12: T064–T070 and T072 together.
- Phases 7–10 are sequential: each rewrites `internal/intent`, and Phase 10's stamps share T038's query file.

### Parallel example: before the formats

```text
T007–T010  internal/psp/, internal/conformance/, psp/*.yaml, testdata/psp/   (US4)
T011–T015  internal/server/scope.go, internal/api, internal/cli, cmd/fylgja/serve.go   (US1)
T016       infrahub/queries/device_config.gql, infrahub/templates/device_config.j2, .infrahub.yml
T027       schema/dcim/
→ then T017–T024 in one run (needs T007–T016)
```

---

## Implementation Strategy

**MVP**: Phases 1–8. After Phase 8 the reader reads the library's DCIM, strict inside the
scope and honest at its edge, proved in tier 1 against recorded answers, with conformance
reported by `schema check`. It reaches a twin only once the host is migrated (Phase 11),
since the template that renders the artifacts needs the operator's push and import.

**Incremental delivery**: the identifiers and the packages' matches → the request's
scope → the template, CTM `2`, the compiler, the formats and the goldens → the schema
directory, test support, the fixture tool and the interim client → conformance → the read →
the record's scope → stages over the new model → the host migrated, imported, re-seeded,
and every tier → the records. Every checkpoint leaves the tree green.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

1. **Run 1** — the baseline: the pure gates and Infrahub's state read, the demo window found (T001). Only this; stop and report.
2. **Run 2** — [operator] the demo window closed with today's tree, D-057 accepted and appended, Constitution 2.0.0, and the plan's four departures settled with FR-040's telling (T002–T005). Stop and report.
3. **Run 3** — the sixteen identifiers, and PSP 0.7: matches, the two rules, the registry's Match, the packages and their defects, the suite's checks (T006–T010). Only these; stop and report.
4. **Run 4** — the request's scope: scopeOf, the API's argument on five operations, the scope carried to every read and input, --scope on the five commands, FYLGJA_DEFAULT_SCOPE on serve, .env.example and the bring-up script (T011–T015). Only these; stop and report.
5. **Run 5** — the template and its query rewritten for the library's kinds, the transforms skill loaded, the predicted renders recorded (T016). Only this; stop and report.
6. **Run 6** — CTM 2 with the 1 frozen, the fixture CTMs, validation and the compiler without iftype, manifest 5 with the 4 frozen, the old reader bridged, then the goldens re-baselined on a commit of their own (T017–T024). Only these; stop at the golden commit and report.
7. **Run 7** — twin.json 8 with the 7 frozen, and the record's provenance in show, verify and step, the 7 record refused by step (T025–T026). Only these; stop and report.
8. **Run 8** — schema/dcim vendored and embedded with its SHA-256 test, the generics and reference schema removed, LoadSchema, and test support's seeds and helpers in the library's kinds, the objects skill loaded (T027–T030). Only these; stop and report.
9. **Run 9** — the fixture tool's flags and -prepare-main's gate, the bring-up script, the interim SDL and typed client from a throwaway branch with the schema document captured, the C4 model and the schema diagram (T031–T034). Only these; stop and report.
10. **Run 10** — conformance: the mapping's table, SchemaInfo and CheckConformance with the five schema findings naming the commit, schema check's line and block (T035–T037). Only these; stop and report.
11. **Run 11** — the read: Devices and Ports, the projection and the cable judgement, the fidelity list, completeness, the summary line, stage.Read without the contract, ctm.version.unsupported, the harness's fake and the read's tier-1 tests (T038–T043). Only these; stop and report.
12. **Run 12** — the read's tier-2 tests written, the C4 intent component, and the step's and the follow's reads under the record's scope (T044–T046). Only these; stop and report.
13. **Run 13** — stages over the new model: the node stamps, the intent events, the staleness rule, scope.empty at the branch point with the checks' identifier (T047–T050). Only these; stop and report.
14. **Run 14** — the stages' and checks' tier-2 tests, the read-only test, what the generics left retired, and tier 3's script (T051–T054). Only these; stop and report.
15. **Run 15** — [operator] FYLGJA_DEFAULT_SCOPE in local/.env and the go-ahead for main's migration (T055). Stop and report.
16. **Run 16** — [live] main migrated by the two documents, the library loaded by -prepare-main and its refusal seen (T056). Stop and report.
17. **Run 17** — [operator] the push to origin's main, and CI's contract job read (T057). Stop and report.
18. **Run 18** — [live] the import, the worker and the server restarted and verified, the fixture re-seeded, the SDL and client from the migrated main, the render checked against the prediction, and the hand scenarios of quickstart §3–§6 (T058–T061). Stop and report.
19. **Run 19** — [live] the contract tier whole beside the server on the bridge (T062). Stop and report.
20. **Run 20** — [live] tier 3 whole and narrowed on a quiet host (T063). Stop and report.
21. **Run 21** — the records: architecture, glossary, development.md, verified-facts.md, README, brief and roadmap, the schema and package READMEs, cli.md and api.md, CLAUDE.md, .env.example and SECURITY.md re-read (T064–T072). Only these; stop and report.
22. **Run 22** — the closing gates and greps (T073). Only this; stop and report.
23. **Run 23** — [operator] the operator's review, commits and the command log (T074). Stop and report.

`converge` follows Run 23.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route"
only up to the next heading.

**For `analyze` to settle**, beside T005's four departures:

- **A platform with no manufacturer.** The spec's Edge Cases says it is "refused as
  unmatched, naming what is missing"; R-03 and [contracts/mapping.md](contracts/mapping.md)
  §4 file it as `platform.missing`. This file builds R-03's (T040). FR-014 and the edge case were amended at `analyze` to R-03's.
- **"The report names the scope read"** (US5 scenario 4). R-17 puts the scope in `twin
  rehearse`'s heading and the document's `subject.scope`. Neither the plan nor the
  rehearsal's contract says whether the markdown comment that `fylgja-twin` posts names
  it. This file builds the heading and the subject alone (T046).
- **SC-006's "no change to what they assert"** for tier 2's stage and check packages. The
  branch point's identifier changes from `contract.node.missing` to `scope.empty`
  (FR-015), so T051 changes that one identifier in their assertions and nothing else. SC-006 and US5's Independent Test were amended at `analyze` to say so.
- **The artifacts predicted before any render** (R-09, R-11). `three-node.json`'s and
  `mixed.json`'s artifacts are written by hand at T016–T019. T060 checks them against a
  real render, and a mismatch costs a second golden commit.
- **The old reader bridged for two runs** (T023), this file's own ordering. It writes a
  truthful mapping (`infrahub-generics`) and the scope it was given, and reads every
  device; no CTM it writes reaches a host.

**Owed from research §4, and where each lands**: the template's render on the library's
kinds (T060); the import of the rewritten query on a `main` holding the library (T058);
`-prepare-main`'s load and `main`'s new hash (T056); the fixture's compiled id (T061) and
the mixed fixture's read (T060, T062); `schema.kind.missing` on a real branch (T062); a
pinned read filtering by tag (T062); a rebase over the library's kinds (T062); the tiers'
timings (T053, T062, T063, T073); the operator's three (T002, T003–T004, T057); the goldens
on their own commit (T024, and T060 if needed); `make diagrams` (T034, T045, T073).
