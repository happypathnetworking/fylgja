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

- [X] T003 [operator] Put [D-057](research.md#3-1) (the CTM is the contract; a reader maps one source's model onto it; the Infrahub reader reads the schema library's DCIM at `26336e9`; it supersedes D-002, D-003 and D-004) to the operator at `analyze`. If accepted, append it to `docs/decisions.md` as D-057 in D-056's format, after D-056 and before "Parked", with `D-002`, `D-003` and `D-004`'s status lines saying "Superseded by D-057" as earlier supersessions did. Then grep `docs/architecture.md` for the old positions (`generics`, `contract version`, `iftype`, `D-002`, `D-003`, `D-004`) and note each hit's line for T064. If declined, record the answer in `research.md` §5 and build nothing from Phase 5 on: Phases 3 and 4 (the package's matches, the request's scope) stand under 1.3.0; everything from T017 removes what its III mandates. Blocks T017 and T035.
  - *2026-10-25 20:53Z, Run 2 of the converge loop (live): left unchecked.* There is no record of the operator accepting D-057: analyze's report and `23b07bf`'s body leave it to this run, and a headless run cannot ask. Once it is accepted, this is mechanical. `docs/decisions.md` has D-056 at line 3442 and "Parked" at 3493. D-002 (line 129), D-003 (173) and D-004 (224) each read `**Status:** Accepted 2026-09-14`; the one earlier supersession (line 3103) appends `; superseded by [D-053](#d-053) on <date>`. The architecture grep, read now and to be read again after the append, matches 14 lines: `generics` 167, 169, 172, 176, 219, 332, 1413; `contract version` 250; `iftype` 198, 211, 213, 361; `D-002` 167; `D-003` 214; `D-004` 216.
  - *2026-10-25, the attended session, under the loop's pause at `e75f9ca`:* **accepted by the operator as drafted** (question 1, answer `1a`). D-057 is appended to `docs/decisions.md` after D-056 and before "Parked", in D-056's format, with its row in the index; D-002, D-003 and D-004's status lines read `Accepted 2026-09-14; superseded by [D-057](#d-057) on 2026-10-25.` The architecture grep, read again after the append, matches the same 14 lines for T064: `generics` 167, 169, 172, 176, 219, 332, 1413; `contract version` 250; `iftype` 198, 211, 213, 361; `D-002` 167; `D-003` 214; `D-004` 216. T017 and T035 no longer wait on this one.

- [X] T004 [operator] Amend the constitution to 2.0.0 as [research §3.2](research.md#3-2) drafts it, citing D-057: in `.specify/memory/constitution.md`, Principle III rewritten ("The CTM Is the Contract; a Reader Maps One Source"), VI reworded (the scope and the mapping in place of the contract version), II's sentence on the matches, the Gate Adjustments' blessed layer (the mapping, D-057, in place of the generics contract, D-002), the Gate Adjustments' CTM bullet and the Development Workflow's tier gate as research §3.2's two added paragraphs give them, the Sync Impact Report and the version line; in `.specify/templates/plan-template.md` (tracked), the Constitution Check's version and row III's text. After T003; blocks T017 and T035.
  - *2026-10-25 20:53Z, Run 2 of the converge loop (live): left unchecked.* It comes after T003, whose acceptance is not on record, and 2.0.0 is the operator's to accept. Governance requires every decision the constitution cites to be *Accepted*, so D-057 lands first. Checked against 1.3.0: every sentence research §3.2 replaces is in the file word for word. They are VI's "and the contract version" (line 107), the CTM bullet (176–179), the generics-contract bullet (181) and the tier gate (194–195). One thing to settle when it is applied: §3.2 says II "gains" its clause but not where. II's sentence ends "…MUST come from the PSP, never from a global constant." (lines 53–54). The plan template is tracked; its version is at line 43 and row III at line 50.
  - *2026-10-25, the attended session, under the loop's pause at `e75f9ca`:* **accepted by the operator as drafted** (question 1, answer `2a`), with II's clause folded into its last sentence, as the attended session proposed and the operator accepted: "Budgets, timeouts, readiness and the manufacturer and platform pairs a package matches MUST come from the PSP, never from a global constant." with D-057 added to II's rationale. `.specify/memory/constitution.md` is 2.0.0 (Last Amended 2026-10-25) with research §3.2's III, VI, Gate Adjustments (the CTM bullet and the mapping in place of the generics contract) and tier gate, and its Sync Impact Report. `.specify/templates/plan-template.md` names 2.0.0, row III reads §3.2's text, and rows II and VI and the blessed layers follow the amended II, VI and gate. T017 and T035 no longer wait on this one.

- [X] T005 [operator] Settle at `analyze` the plan's four departures from the spec (plan, "Post-design re-check"), and amend `spec.md` where the answer changes its text: (a) `stage list --scope` and `stage.list`'s `scope` argument (R-04), which FR-017 does not name; (b) the migration as two removal documents, implementers first (R-14, research §1.9), where FR-040 says one step; (c) the template's import as the gate before the fixture's re-seed and tier 2, not only before tier 3 (R-14; FR-040); (d) the open demo window as a precondition (T002). With them, tell the operator what FR-040 requires before the work starts: the template, query and checks change needs their push to `origin`'s `main` (T057) before it can be imported; `main`'s schema is migrated (T056); and both fixtures are re-seeded (T060). Record the operator's acknowledgement in this task's note. This file builds the plan's reading of (a)–(d); a different answer changes T012–T014 (a) and Phase 11's order (b, c). `analyze` on 2026-10-25 amended FR-017 (a) and FR-040 (b, c) to the plan's reading, and (d) is T002; what remains here is the telling and the acknowledgement.
  - *2026-10-25 20:53Z, Run 2 of the converge loop (live): left unchecked.* The acknowledgement is the operator's. (a)–(c) stand in `spec.md` as analyze amended them: FR-017 (line 415) names `stage list`, and FR-040 (line 504) gives the two removal documents and the import before the re-seed and tier 2. (d) is T002, now closed. The telling, put to the operator in this run's report: (1) the template, query and checks change reaches Infrahub only after the operator merges the whole branch into `main` and pushes `origin`'s `main` (T057), and it is then imported (T058). The fixtures are re-seeded and tier 2 runs only after that, so `main` carries code that tiers 2 and 3 have not yet proved on this host. (2) `main`'s schema is migrated (T056), this feature's one lasting write to `main`: two removal documents, the reference kinds first, then the library loaded by `-prepare-main`. (3) Both fixtures, `fylgja-fixture` and the mixed one, are deleted and re-seeded in the library's kinds (T060), and their compiled ids move.
  - *2026-10-25, the attended session, under the loop's pause at `e75f9ca`:* **acknowledged by the operator** (question 1, answer `3a`), with no reservation: the push and import before the re-seed and tier 2 (T057, T058), `main`'s migration (T056), and both fixtures re-seeded with their compiled ids moved (T060), as Run 2's note above tells them.

**Checkpoint**: baseline green; window closed; D-057 and 2.0.0 accepted before Phase 5.

---

## Phase 2: Foundational — the identifiers

**Purpose**: the sixteen identifiers of R-21, so every later task files them by constant.
The eight retired ones are removed by the tasks that remove their last users (T020, T036,
T042, T050), and T053 checks all eight are gone.

- [X] T006 [P] In `internal/findings/finding.go`, add the sixteen rule constants of [contracts/scope-and-commands.md](contracts/scope-and-commands.md) "The identifiers" (`scope.invalid`, `scope.unset`, `scope.empty`, `schema.kind.missing`, `schema.field.missing`, `schema.field.mismatch`, `schema.choice.missing`, `schema.used_by.missing`, `platform.missing`, `platform.unmatched`, `omit.cable.ends`, `omit.cable.endpoint`, `omit.cable.outside_scope`, `ctm.version.unsupported`, `psp.matches.missing`, `psp.matches.duplicate`). Each gets the house comment (`// rejection, exit 2, start: <object>; <when>`), with the table's severity, exit, step and object exactly. Register each in `internal/findings/finding_test.go`'s `dataModelRules`. Add `Subject.Scope string` (`json:"scope,omitempty"`) in `internal/findings/render.go`. Give `contracts/findings.schema.json` (still version `1`) `subject.scope` as an optional string matching `^tag:\S+$`, and add a sentence on 017 to its description. Extend `decode_test.go` so it round-trips a subject with a scope. Leave every retired identifier in place.
  - *2026-10-25 21:15Z, at `8acf30d`, Run 3 of the converge loop:* done. The sixteen constants are one block in `finding.go`, "017, the DCIM reader and the scope a request names", in the contract table's order (`RuleScopeInvalid` … `RulePSPMatchesDuplicate`), each with the house comment carrying the table's severity, exit, step and object; `scope.empty` and `schema.kind.missing` carry their second step in parentheses. `dataModelRules` gains them as an appended 017 block; the eight retired identifiers stay in both lists. `Subject.Scope` (`json:"scope,omitempty"`) follows `Stage`. `contracts/findings.schema.json` (still `1`) has `subject.scope` matching `^tag:\S+$` and a 017 sentence in its description. `decode_test.go` round-trips three scoped documents (`scopedDocuments`: a read under a scope, a stage's read under one, a refusal with no scope read), and `TestSubjectScopeSatisfiesTheContract` holds them valid against the current contract and refuses `fylgja`, `tag:`, `tag:a b`, `group:x` and `Tag:fylgja` as a subject's scope. Nothing files the new rules yet.

---

## Phase 3: User Story 4 — A support package says which platforms it is (Priority: P2)

**Goal**: format `0.7`: each package declares `platform.matches`; the registry matches
exactly; the suite refuses no match and a shared match (FR-025–FR-027).

**Independent Test**: both shipped packages pass the suite's pure half with their
matches; `testdata/psp/defects/matches-missing.yaml` and `matches-shared.yaml` fail it by
name; `version-0-6-m11.yaml` is refused naming `0.7`.

- [X] T007 [US4] Freeze first: copy `psp/nokia_srlinux.yaml` byte for byte to `testdata/psp/defects/version-0-6-m11.yaml`, as `version-0-5-m10.yaml` was kept. Then format `0.7` in `internal/psp/types.go`: `Identity.Matches []Match` (`yaml:"matches" json:"matches"`), `Match{Manufacturer, Platform string}` (`yaml`/`json` `manufacturer`, `platform`), `FormatVersion = "0.7"` (data-model §4). In `psp/psp.schema.json`, and in `contracts/psp.schema.json`, which is byte-identical to it today and stays so: `platform.matches` required, `minItems: 1`, each item `{manufacturer, platform}`, both required, `minLength: 1`, `additionalProperties: false`. Give it the description of [contracts/package-matches.md](contracts/package-matches.md) "The field", including "both exactly, letter case and spacing included". `psp.version.unknown` names `0.7` (`declares format version "0.6", this build understands "0.7"`): pin it with `version-0-6-m11.yaml` in `internal/psp/validate_test.go`, beside the `0.5` case.
  - *2026-10-25 21:15Z, at `8acf30d`, Run 3 of the converge loop:* done. `version-0-6-m11.yaml` was copied before any package changed, and `TestM11ShippedPackageIsVersionUnknown` holds it to M11's bytes (`0.6`, `link_change`, no `matches:` key). Format `0.7` as data-model §4 gives it, with `Match.String()` (`manufacturer "…", platform "…"`, quoted so case and spacing show) for the findings. Both schema copies are one file again: `$id …/psp/v0.7`, the title, `psp_version` const `0.7`, `platform.matches` required with the contract's description whole, and a 017 sentence on the format's description. `psp.version.unknown` names `0.7` for `version-0-6-m11.yaml` in the defect table and its own test, beside the `0.5` (`version-0-5-m10`) and `0.3` cases, whose messages moved to `0.7`. One more file moved, by the convention `TestPreviousFormatPackageIsVersionUnknown` states (the one-behind fixture is renamed with each bump): `version-0-5.yaml` is now `version-0-6.yaml`, the shipped package with its version line alone at `0.6`; the worker's, the server's and the CLI's tests that used it follow, and the worker's previous-format test gains `version-0-6-m11.yaml`. Left for a later task: the schema's `nos` still says "Matches FylgjaPlatform.nos", which holds while the generics reader runs (until T039), and `psp/README.md` still documents `0.6` (T069).

- [X] T008 [US4] The rules and the registry ([contracts/package-matches.md](contracts/package-matches.md) "The rules", "The registry").
  - `psp.matches.missing` in `internal/psp/consistency.go`'s `checkConsistency`: no match, or a pair with an empty name. Object: the package path.
  - `checkDuplicateMatch` over a set of packages: `psp.matches.duplicate`, naming both packages and the pair. `psp validate` runs it over the files given (`internal/server/validate.go`), beside `psp.identity.duplicate`.
  - In `internal/psp/load.go`, `Load` indexes the matches after shadowing and refuses the registry on a shared pair, as it refuses an invalid override, so that `fylgja serve` and `fylgja worker run` refuse at start.
  - `Registry.Match(manufacturer, platform string) (*PSP, bool)`, exact on both strings.
  - Tests in `internal/psp/load_test.go` and `validate_test.go`: exact match; `nokia` / `SR-Linux` and `Nokia` / `SR Linux ` (trailing space) miss; an override sharing a pair refuses `Load`. One case each in `cmd/fylgja/serve_test.go` and `worker_test.go`: a `FYLGJA_PSP_DIR` holding a package that shares a pair refuses the start, naming `psp.matches.duplicate`.
  - *2026-10-25 21:15Z, at `8acf30d`, Run 3 of the converge loop:* done. `checkMatches` files `psp.matches.missing` at the package path for no pair, and per pair with an empty name. It fires beside `psp.version.unknown` on every package before `0.7`, since each lacks the field; `TestM10ShippedPackageIsVersionUnknown` and `TestM11ShippedPackageIsVersionUnknown` assert it once. `checkDuplicateMatch` runs in `validate()` beside `checkDuplicateIdentity`, so `psp validate`, whose server handler calls `psp.ValidateFiles`, gets it with no code change there (its comment now names it). Its message names the pair and both packages by id and path, at the later file. A pair named twice in one package is not a defect. `Load` builds the match join in `index()`, which now returns the refusal as an `*InvalidError` carrying `psp.matches.duplicate`, embedded packages first so the finding is at the override's file; an override shadowing an embedded package by NOS takes its pair with it and loads. `Registry.Match` is exact on both strings. Tests: `TestRegistryMatchesExactly` (both shipped pairs and an override's; `nokia` / `SR-Linux`, `Nokia` / `SR Linux `, a leading space, crossed and empty names miss), `TestOverrideSharingAPairIsRefusedAtLoad`, `matches-shared` in `TestInvalidOverrideIsRefusedAtLoad`, `TestSharedMatchIsFoundAcrossTheSet` (the CLI's `psp validate`), `TestWorkerRefusesAPackageSharingAPair`, and the server case "an override package sharing a pair, from FYLGJA_PSP_DIR". A byte copy of the shipped package now draws both set rules: `TestDuplicateIdentityAcrossFiles` and `TestValidateFilesNamesThePathsGiven` assert both. The product comments name a fictional pair (`Acme` / `AcmeOS`), since `TestCompilerNamesNoPlatform` refuses a platform's name in `internal/psp`.

- [X] T009 [US4] The packages. Move `psp/nokia_srlinux.yaml` and `psp/arista_eos.yaml` to `psp_version: "0.7"`, with `matches: [{manufacturer: Nokia, platform: SR Linux}]` and `[{manufacturer: Arista, platform: EOS}]` (FR-027, R-08). Every `testdata/psp/` package meant to load moves to `0.7` with pairs of its own (`heterogeneous/*.yaml`, `lossy/chassisos.yaml`; for example `FastOS Inc` / `FastOS`), no two sharing one. Every defect under `testdata/psp/defects/` moves to `0.7` with a pair of its own (no two sharing one), so that each still fails by the rule it names and by no other; `version-0-3-m5.yaml`, `version-0-5-m10.yaml` and `version-0-6-m11.yaml` keep their versions. Add `testdata/psp/defects/matches-missing.yaml` (the SR Linux package with `matches: []`) and `matches-shared.yaml` (a third package naming `Nokia` / `SR Linux`). Each must fail its rule in `internal/psp/validate_test.go`'s defect table. `TestShippedPackagesAreValidAndEmbedded` passes at `0.7`.
  - *2026-10-25 21:15Z, at `8acf30d`, Run 3 of the converge loop:* done. Shipped: `Nokia` / `SR Linux` and `Arista` / `EOS`, each under a comment saying the names are compared exactly. Packages meant to load: `FastOS Inc` / `FastOS`, `SlowOS Inc` / `SlowOS`, `ChassisOS Inc` / `ChassisOS`. **One reading taken, for review**: each defect carries the pair of the package it is derived from, not one of its own. That is 39 SR Linux-derived defects at `Nokia` / `SR Linux`, `readiness-await-push-no-push.yaml` at `Arista` / `EOS`, and `management-node-name-reachable.yaml` at the chassisos pair. The reasons: the defects already share their base's id and NOS, so no two are ever validated in one set (they would collide by identity first); an override copy shadows its base by NOS and takes the pair with it; and a pair of its own would make each defect two changes from its base, breaking `duplicate-identity.yaml`'s byte identity and `version-0-6.yaml`'s one-line difference, both of which tests hold. The purpose clause holds: every defect's diff against its base was checked unchanged but for the version line, and each still fails by its named rule alone in `TestDefectsAreNamed`. `several.yaml` and `version-unknown.yaml` keep `0.9` and gain the pair. The frozen `0.3`, `0.5` and `0.6` copies are untouched. `matches-missing.yaml` is the shipped package with `matches: []`. `matches-shared.yaml` is `fastos.yaml` as `sharedos` (its own id, NOS, kind and image) naming `Nokia` / `SR Linux`: valid alone and refused beside the shipped package. The defect table gains a `with` set for it. Three tier-1 tests that derive `acme_os` from the shipped package (`internal/compiler/fidelity_test.go`, `internal/validate/rules_test.go`, `internal/stages/stale_test.go`) give it `Acme` / `AcmeOS`, or the registry refuses it. `TestShippedPackagesAreValidAndEmbedded` passes at `0.7`.

- [X] T010 [US4] The conformance suite's pure half (`internal/conformance/pure.go`): the check `matches`, which requires at least one pair with both names non-empty and otherwise says `package <id> (<path>): matches: declared <n> pairs, produced none`. Add `TestShippedPackagesShareNoMatch` in `internal/conformance/pure_test.go`, over every package meant to load (shipped and `testdata/psp/`'s), holding the pairs pairwise distinct. The two defect fixtures of T009 each fail it by name. The boot half is unchanged.
  - *2026-10-25 21:15Z, at `8acf30d`, Run 3 of the converge loop:* done. `CheckMatches` (`matches`) runs after `link_change` and is in `PureChecks`, so `TestPureHalf` runs it on every package meant to load. Its failure reads `package <id> (<path>): matches: declared 0 pairs, produced none`; a single pair with an empty name reads `declared 1 pair`, singular where the contract's `<n> pairs` would say "1 pairs". `SharedMatches(pkgs)` is the set check, worded as the suite words a failure: `package sharedos (<path>): matches: declared manufacturer "Nokia", platform "SR Linux", produced the pair package nokia_srlinux (<path>) declares`. `TestPureHalfMatches` covers both shipped pairs, `matches-missing.yaml` and an emptied platform name. `TestShippedPackagesShareNoMatch` runs over the five packages meant to load, then shows `matches-shared.yaml` failing the set by name (and passing the per-package check), and `matches-missing.yaml` failing the per-package check by name (and sharing nothing). The boot half is unchanged.

  *Run 3's checkpoint, 21:15Z*: `make build` static; `make test` uncached 34.2 s wall (load average 5.1 before, 4.6 after); `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; no golden moved. Every package is at `0.7`, and nothing reads `matches` yet. These tasks name no tier-2 test, so none was run. No twin, worker or server was touched, and nothing was written to Infrahub. The C4 model needs no redraw: `internal/psp` gained no import beyond `fmt`, and no component's relations moved.

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

- [X] T011 [US1] Create `internal/server/scope.go` with `scopeOf(opts, given string, givenSet bool) (string, error)` (data-model §9). It returns the request's scope when given, else `Server.DefaultScope`. It refuses `scope.invalid` (object the value given; the message names the accepted form `tag:<name>`) for anything not matching `^tag:\S+$`, the empty value included. It refuses `scope.unset` (object `FYLGJA_DEFAULT_SCOPE`; the message names the variable) when neither is set. Both refusals are at step `start`, exit 2. Add `DefaultScope string` to `server.Server` in `internal/server/server.go`. Table tests in `internal/server/scope_test.go`: the default, the argument over the default, `fylgja`, `group:x`, `tag:`, `tag:a b`, `""`, unset.
  - *2026-10-25 21:46Z, at `b650932`, Run 4 of the converge loop:* done. `internal/server/scope.go` holds `EnvDefaultScope` (`FYLGJA_DEFAULT_SCOPE`), `ValidScope` (`^tag:\S+$`, which `fylgja serve` checks its default with too, T015) and `scopeOf`. **One departure, for review**: the signature is `scopeOf(opts, op, subject, given, givenSet)`, op and subject added, since each refusal is the command's document and names its subject, and a handler's options name no operation of their own (the tests call handlers with options whose call is `test`). `scope.invalid` names the value given and says `--scope "<value>" is not a scope: the accepted form is tag:<name>, the literal tag: and one word, the tag every device of the twin carries`; `scope.unset` names `FYLGJA_DEFAULT_SCOPE` and says `no --scope was given and the server has no default: name one with --scope tag:<name>, or set FYLGJA_DEFAULT_SCOPE where fylgja serve starts`; both exit 2 at step `start`, on `intent.read` too, as the contract's table gives them (unlike `intent.at.precision`, which carries no step). `Server.DefaultScope` is in `server.go`. `TestScopeOf` holds the nine cases the task names (the default, the argument over it, the argument with no default, `fylgja`, `group:x`, `tag:`, `tag:a b`, `""`, unset); `TestValidScope` the rule alone.

- [X] T012 [US1] The API's argument (R-16; [contracts/scope-and-commands.md](contracts/scope-and-commands.md) "The API"). In `internal/server/handlers.go`'s `operationArgs` (wherever the operations' arguments are declared), add `"scope": argString` to `twin.create`, `twin.rehearse`, `intent.read`, `stage.plan` and `stage.list`. `twin.step` with `scope` is `400`, `the request is not one: twin.step takes no argument "scope"`. In `contracts/api.schema.json`, the five operations' `args` gain `scope` (an optional string) with a 017 sentence. The API's version stays `1`. Tests in `internal/api/wire_test.go` and `internal/server/server_test.go`: each frame is valid against the schema, `twin.step`'s refusal, and a `1` client that sends no `scope` is served.
  - *2026-10-25 21:46Z, at `b650932`, Run 4 of the converge loop:* done. `operationArgs` gives the five `"scope": argString`, so `twin.step` with `scope` is 400 `the request is not one: twin.step takes no argument "scope"` by the existing strict decode. `contracts/api.schema.json`'s five `args` gain `scope` (a string, described as `--scope` as given, absent being the default and present and empty `--scope=`), and its description a 017 sentence; the version stays `1`. `TestEveryOperationsRequestSatisfiesTheContract` sends `scope` on the five (one of them `""`) and holds each request to the schema, each of the five valid without it, `scope` not a string invalid, and `scope` invalid on the eight operations that take none. `TestAnArgumentNotTakenIsUnreadable` adds `twin.step`'s and `schema.check`'s refusals and two of kind, and the five answer 200 with `tag:fylgja` and with `""` (the server's `scope.invalid` to refuse, not the transport's); its existing loop of `{"args":{}}` on every operation is the client of `1` that sends no scope.

- [X] T013 [US1] Carry the scope through every read (R-04). In `internal/server/create.go`, `rehearse.go`, `read.go` and `stages.go` (plan and list), call `scopeOf` at `start`: after `--branch`'s and `--stage`'s guards, before the packages load and before any connection. Set `findings.Subject.Scope` on the document. Pass the scope on:
  - `intent.Config.Scope` (`internal/intent/client.go`: the tag's name, after `tag:`);
  - `stage.Read(ctx, branch, at, scope, reg, observedAt)` (`internal/stage/stage.go`);
  - `stages.Stamper.Stamps(ctx, branch, at, scope)`, with `stages.Plan`, `List` and `Resolve` carrying it (`internal/stages/`);
  - `provision.ProvisionInput.Scope`, `ReadIntentInput.Scope` and `ReconcileInput.Scope` in `internal/provision/types.go` (`json:"scope,omitempty"`), the activities passing it to `stage.Read`, and the follow's `ReconcileInput` taking `ProvisionInput.Scope`.

  The old generics reader takes `Config.Scope` and does not filter by it yet. Say so in a comment naming T039. The nine recorded histories in `internal/provision/workflow_replay_test.go` must replay unchanged. Every caller and fake of the changed signatures moves in this task.
  - *2026-10-25 21:46Z, at `b650932`, Run 4 of the converge loop:* done. `intent.Config.Scope` (the tag's name; the comment says the generics reader is given it and does not filter by it until T039), `intent.ScopePrefix` and `intent.ScopeTag`. `stage.Read(ctx, branch, at, scope, reg, observedAt)`. In `internal/stages`, `Stamper.Stamps(ctx, branch, at, scope)`, and the scope rides `Change.Scope`, set by `Find` and `List`: every stage of one proposed change, its head's, its staleness's and the destination's stamps and each stage's read, is under the one scope the command gave (`Plan(…, branch, scope, …)`, `List(…, branch, scope, record)`, `Resolve(…, ref, scope, now)`, `Find(…, branch, scope)`; `Build` and `ResolveFrom` read it from the change; `Pipeline.Read` takes it). The server calls `scopeOf` in create, rehearse, read, stage plan and stage list after their reference guards and before `psp.Load`, sets `subject.scope` once resolved (so `stage list`'s and `stage plan`'s documents now carry a subject, `{scope}`, where they carried none), and passes it to `resolveStage`, `planStages` (kept on `plannedStages` for the rehearsal's baseline input and its re-listing) and the dry run. `provision.ProvisionInput.Scope`, `ReadIntentInput.Scope` and `ReconcileInput.Scope`, each `omitempty`; **one addition the task does not name**: `StartFollowingInput.Scope`, the one path from a run's input to the Schedule's `ReconcileInput`, so a following twin's checks read under its scope and its rebuild records it. `twin step` finds its proposed change under `""` until the record carries `provenance.scope` (T025) and the step reads it (T046), said in a comment there. `findings.Subject.Scope`'s comment and `findings.schema.json`'s description now say it is named once resolved, before the packages load. Tests: `TestEveryReadIsUnderTheScopeGiven` (`internal/stages`: a plan, a listing, a resolution and a build read every stamp and stage under the scope given); `TestProvisionReadsAndFollowsUnderItsScope`, `TestReconcileReadsAndRebuildsUnderItsScope`, and `TestStartFollowingActivity`'s Schedule args with the scope; the rehearsal's baseline input carries it (`rehearse_test.go`). The nine recorded histories replay unchanged. Every caller and fake moved, the contract-tagged ones included (`go vet -tags contract,fixture,e2e` clean).

- [X] T014 [US1] The client (`internal/cli/`): `--scope` on `twin create`, `twin rehearse`, `intent read`, `stage plan` and `stage list`, sent as `args.scope` only when given (so `--scope=` is sent as `""` and refused by the server). `twin step` gets no flag, so cobra refuses `--scope` (`unknown flag: --scope`, exit 2, no request). The harness's `server.Server` sets `DefaultScope: "tag:fylgja"`. Tests through the harness for each of the five commands: `scope.invalid` for `--scope fylgja` and `--scope=`; `scope.unset` against a harness server with no default; both before any connection, with nothing dialled (the fake Infrahub and the workflow service record no request). Plus `twin step --scope tag:fylgja` refused by cobra.
  - *2026-10-25 21:46Z, at `b650932`, Run 4 of the converge loop:* done. `--scope` on `twin create`, `twin rehearse`, `intent read`, `stage plan` and `stage list` (`given.scope` sends it whenever the flag was given, `""` included; `scopeUsage` is the help). `twin step` has none, so cobra refuses it. The harness hands the server `defaultScope`, a seam set to `tag:fylgja` that a test empties. `TestRefusalsBeforeAnyConnectionAreTheServers` gains fifteen cases (each command with `--scope fylgja`, `--scope=` and no scope beside no default), each the server's document, exit 2 at `start`, with neither the workflow service dialled nor the fake Infrahub asked; `TestStepTakesNoBranchFlags` gains `--scope=tag:fylgja` (`unknown flag: --scope`, nothing read); `TestCreateCarriesItsScope` holds the run's input and the subject to the scope given and to the default. The tests pinning a create's exact input or subject now carry the default. **One test-support change, for review**: a document validated against a frozen contract older than 017 (`validateDocument`, `validateWithShow` for M4–M7) is validated whole against the current one when its subject names a scope, and with the scope left out against the older (`withoutScope`), as `show_test.go` leaves out `stage` for M10's.

- [X] T015 [US1] The server's setting ([contracts/scope-and-commands.md](contracts/scope-and-commands.md) "The server").
  - `cmd/fylgja/serve.go` reads `FYLGJA_DEFAULT_SCOPE` and reports, after the state root line, `fylgja serve: default scope: tag:fylgja`, or `fylgja serve: default scope: unset (a request that names no scope is refused)` when unset or empty. A value not matching `^tag:\S+$` refuses the start: `fylgja serve: FYLGJA_DEFAULT_SCOPE <value> is not tag:<name>`, exit 2, before it listens. The worker never reads it.
  - Tests in `cmd/fylgja/serve_test.go`: a set default, an unset default and a malformed one.
  - `.env.example` documents the name under the server's variables.
  - `scripts/bring-up.sh` scaffolds `FYLGJA_DEFAULT_SCOPE` as `tag:fylgja` in `env_value`. The script keeps an existing `local/.env` byte for byte, so on this host the name is added by the operator (T055). Read how the script judges an existing file's names (around its `grep -qx FYLGJA_API_TOKEN`), and make a missing `FYLGJA_DEFAULT_SCOPE` a reported note rather than a refusal, since the server starts without it.
  - `shellcheck scripts/bring-up.sh scripts/e2e.sh` is clean.
  - *2026-10-25 21:46Z, at `b650932`, Run 4 of the converge loop:* done. `fylgja serve` reads `FYLGJA_DEFAULT_SCOPE` after the token and `--listen` checks and before the state root, refusing a value that is not `tag:<name>` (`fylgja serve: FYLGJA_DEFAULT_SCOPE <value> is not tag:<name>`, exit 2); unset or empty is no default. The report's line after the state root is `default scope: tag:fylgja` or `default scope: unset (a request that names no scope is refused)`; `--help` names the variable. The worker reads nothing new. `cmd/fylgja/serve_test.go`: `TestServeReportsAndServesItsDefaultScope` (set: the line, and a request naming no scope goes on to Infrahub; unset and empty: the line, and such a request is `scope.unset` naming the variable, Infrahub never dialled), two refusal cases in `TestServeRefusesToStartInOrder` (`fylgja`, before an invalid package and an unresolvable state root, and `tag:a b`), and the report tests moved to the new line; `serveEnvironment` sets `tag:fylgja`, so an operator's own environment cannot change the report. `.env.example` documents it under the server's variables, read by the server alone. `scripts/bring-up.sh` scaffolds `tag:fylgja` in `env_value`, and a kept `local/.env` naming no `FYLGJA_DEFAULT_SCOPE` (read by name with `grep -q`, never a value) is the report's `local/.env:` line saying so, with the line to add, never a refusal: the script judged no kept file's names before (the `grep -qx FYLGJA_API_TOKEN` it has reads the task workers' container environment). Simulated against two sample files, since the script needs sudo; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean. **What the operator needs before T055**: a server from this tree reading a `local/.env` without the variable refuses every request that names no scope, so Infrahub's checks (which send none) and tier 3 (whose server inherits `local/.env`) would be `scope.unset`; the variable is added (T055) before the server on the bridge is restarted from this tree. The running server and worker were not touched.

  *Run 4's checkpoint, 21:46Z*: `make build` static; `make test` uncached 42.4 s wall with the changed packages' test binaries compiled cold (load average 1.4 before, 4.3 after), then 33.9 s with the build cache warm (4.0, 5.1); `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean; no golden moved. Every refusal of the scope is proved through the harness before any connection, and the scope reaches every read and input as data; nothing filters by it yet (T039). These tasks name no tier-2 test, so none was run; the contract-tagged tests whose calls moved (`internal/stages`, `internal/stage`) compile. No twin, worker or server was touched, and nothing was written to Infrahub. The C4 model needs no redraw: no package gained an import of another, and no component's relations moved.

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

- [X] T016 [P] Load the `infrahub:infrahub-managing-transforms` skill, and read its SKILL.md, `rules/queries-union-fragments.md` and `infrahub-common/rules/deployment-gql-dry-run.md` before editing. Apply them where `CLAUDE.md` does not decide otherwise (`.venv/bin/infrahubctl`, no `uv`/`poetry`). Then rewrite, as R-11 and [contracts/mapping.md](contracts/mapping.md) give them:
  - `infrahub/queries/device_config.gql`: research §1.6's template query, `DcimDevice(name__value: $device)` with `description`, `platform { node { name manufacturer { node { name } } } }`, and `interfaces { edges { node { __typename name status role ... on InterfacePhysical { connector { node { connected_endpoints { edges { node { ... on DcimInterface { name device { node { name } } } } } } } } } } } }`.
  - `infrahub/templates/device_config.j2`: one file for both platforms. It takes the EOS dialect when `platform.node.name.value == 'EOS'` and the SR Linux one otherwise (a device with no platform included, so that the pipeline never fails). It renders only interfaces whose `__typename` is `InterfacePhysical`: a management-role port as the comment it is today; any other port configured with its far end's `<device> <port>` as its description, and `shutdown` / `admin-state disable` when `status == disabled`. It renders no loopback and no virtual interface. The header's second line is `# platform <Manufacturer> <Platform>; <description>`.
  - `.infrahub.yml`: the definition's description. The definition itself is unchanged (FR-034).

  `infrahub_yaml_test.go` stays green. Then write in `research.md` a new §5 ("Verified at implement"), §5.1: the exact bytes the template renders for `n1`, `n2` and `n3` of the three-node fixture and for `s1`, `e1` and `e2` of the mixed one (data-model §12, R-15, with `description` `FYLGJA-MARKER-fixture` and the mixed seed's marker), worked by hand from the template's text. Say that they are predicted, to be checked at T060.
  - *2026-10-25 22:06Z, at `9255232`, Run 5 of the converge loop:* done. The skill was loaded, and its SKILL.md, `rules/jinja2-template.md`, `rules/queries-union-fragments.md` and `infrahub-common/rules/deployment-gql-dry-run.md` were read before any edit.
    - **The query**: `device_config.gql` is research §1.6's query, by name. The interface's `__typename`, `name`, `status` and `role` are read on `DcimInterface`. The cable is reached through `... on InterfacePhysical`'s `connector`, and its ends through `... on DcimInterface`.
    - **The template**: still one file. The dialect is EOS when the platform's name is `EOS`, else SR Linux. A null platform and a null manufacturer are guarded, since the SDK's file-based environment fails an attribute read on a null node. The loop takes the physical ports alone, by a loop filter on `__typename`, which answers the concrete kind. A `management` role renders today's comment. Any other port takes its far end and an admin state from `status == disabled`, each dialect's lines otherwise as today's. The header's second line is `platform <Manufacturer> <Platform>`, then `; <description>` when the device has one, and loses the leading space when there is no manufacturer.
    - **`.infrahub.yml`**: the transform's description and the file's head comment changed. The definition is unchanged. `TestInfrahubYAMLRegistersTheChecks` is green.
    - **Research §5.1** holds the six predicted documents, each with its MD5 for T019.
    - **The prediction was checked locally, ahead of the import.** `infrahubctl render` of today's template on `fylgja-fixture` (read-only) reproduces the three live artifact checksums. The rewritten template then rendered the six devices byte-identical to the prediction, on the throwaway branch `fylgja-test-017-t016` with the library loaded and both fixtures seeded. That run was also the skill's dry-run of the query. The probes rendered without failing: no platform, no manufacturer, a disabled port, a three-ended and a one-ended cable, and two virtual interfaces, which were skipped. The branch was deleted afterwards.
    - **For review**:
      - The mixed predictions carry `FYLGJA-MARKER-mixed-fixture`, the suffix rule applied to `mixed.json`'s branch.
      - A device with no description renders no `; `.
      - The EOS dialect keeps today's unindented `description` and `no shutdown`.
      - `docs/c4/workspace.dsl` still says the artifacts repository renders "from the Fylgja generics" until T034 redraws it.
      - Until T058 imports this commit, `scripts/e2e.sh`'s case 9 refuses the tree, because `infrahub/` and `.infrahub.yml` differ from the imported commit.

  *Run 5's checkpoint, 22:06Z*: `make build` static; `make test` uncached 33.8 s wall (load average 2.8 before, 4.4 after); `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; no golden moved. T016 names no tier-2 test, so none was run. Infrahub was written to only on the throwaway branch, which is gone. `Branch` lists `main` and `fylgja-fixture` alone, and `main`'s hash is `e43a1cde…` with no `Dcim*` kind. No twin was booted. The worker and the server were not touched. Both started at 20:55:59Z, before Run 4's commits, and after this run's build both `/proc/<pid>/exe` read `(deleted)`; T059 restarts them.

- [X] T017 The CTM's contract files (R-06; [contracts/formats.md](contracts/formats.md) "The frozen copies"). Copy the current `contracts/ctm.schema.json` unchanged to `internal/ctm/testdata/contracts/017-dcim-reader/ctm.schema.json` (the frozen `1`). Then copy [contracts/ctm.schema.json](contracts/ctm.schema.json) (this feature's, `$id …/contracts/ctm/v2`) to `contracts/ctm.schema.json`. Copy the current `testdata/ctm/three-node.json` unchanged to `testdata/ctm/defects/version-1.json` (a `1` fixture, valid against the frozen copy).
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. `contracts/ctm.schema.json` is this feature's (`$id …/contracts/ctm/v2`). The `1` is frozen at `internal/ctm/testdata/contracts/017-dcim-reader/ctm.schema.json`, and `testdata/ctm/defects/version-1.json` is today's `three-node.json`, unchanged. `TestVersion1IsRefused` validates it against the frozen copy, and `ctm`'s `deliberatelyInvalidFixtures` lists it against the current one. `frozenContractCopies` stays 30 until T025; the glob now finds 32.

- [X] T018 CTM `2` in `internal/ctm/types.go` and `json.go` (data-model §2):
  - **Changed**: `Envelope{Branch, At, ObservedAt, SchemaHash, Scope, Mapping, Fidelity}`, with `fidelity` sorted by (disposition, object) and written as `[]`, never `null`; `Mapping{Reader, Model, Version}`; `FidelityRow{Disposition, Object, Source, Reason}`; `Platform{Package, Version (omitempty)}`; `Interface{Name, MgmtOnly, Enabled, Link, Provenance}`; `Device` without `Role` and `Site`; `Version = "2"`.
  - **New constants**: `ReaderInfrahubDCIM = "infrahub-dcim"`, `ModelSchemaLibrary = "opsmill/schema-library"`, `ModelVersion = "26336e9"`.
  - **Gone**: the `Iftype*` constants, `KnownIftypes`, `ImplementedIftypes`, `Address`, `Envelope.ContractVersion`, `Normalize`'s `Family` and its address sort. `ContractVersion`, `ContractKind`, `RequiredGenerics`, `DeviceGeneric` and `ArtifactTargetGeneric` stay until their last users go (T036, T042, T048, T053): give each a plain comment naming 017's removal, not a `Deprecated:` marker, which lint would flag.
  - **`Unmarshal`** refuses another `ctm_version`, naming both (`unsupported ctm_version "1", expected "2"`).
  - **Tests in `internal/ctm/json_test.go`**: `TestVersion1IsRefused`, reading `testdata/ctm/defects/version-1.json` (valid against the frozen `1`) and refused naming both versions. `TestCTMFixturesSatisfyContract`, `TestMarshalledCTMSatisfiesContract` and `TestWellFormedDefectFixturesSatisfyContract` over T019's fixtures. The canonical-order and `Normalize` cases moved to the new fields. `TestDeviceFieldOrderFollowsTheContract` on the new device.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. The types are data-model §2's, with the three constants and the two dispositions `FidelityApproximated` and `FidelityOmitted`. `Normalize` fills `fidelity` with `[]` and sorts it by (disposition, object).
    - **`Unmarshal` reads `ctm_version` first, on its own.** A `1` carries `contract_version` and `iftype`, so the strict decode would refuse it for an unknown field before the version was looked at. It is now refused as `unsupported ctm_version "1", expected "2"`.
    - **Tests**: `TestVersion1IsRefused`, and the canonical-order, round-trip and `Normalize` cases on the new envelope, including the fidelity sort and `[]`. The `1`-only cases are gone: address families, the old envelope.

- [X] T019 The fixture CTMs under `testdata/ctm/` move to `2` (R-09): `three-node.json`, `mixed.json`, `lossy.json`, `mgmt-link.json`, `no-mgmt.json`, `observed-later.json`, `two-mgmt.json` and the three `*.shuffled.json`. Each loses `lo0` and every non-port interface, `role`, `site`, `iftype`, `parent` and `addresses`. Each `platform` becomes `{"package": "<platform.id>"}` (`nokia_srlinux`, `arista_eos`, the lossy package's id). The envelope drops `contract_version` and gains `scope: "tag:fylgja"`, `mapping: {reader: "infrahub-dcim", model: "opsmill/schema-library", version: "26336e9"}`, and `fidelity` holding exactly [contracts/mapping.md](contracts/mapping.md) §5's three rows, sorted:
  - `{approximated, interface.enabled, InterfacePhysical.status, "a port is enabled unless its status is disabled; the library's status is not an admin state"}`
  - `{approximated, interface.mgmt_only, InterfacePhysical.role, "the management port is the port whose role is management; the library has no management-only flag"}`
  - `{omitted, platform.version, DcimPlatform, "the library's platform carries no version"}`

  `three-node.json`'s and `mixed.json`'s artifacts (and their shuffled copies') are T016's predicted bytes, with their checksums recomputed as the fixture's own rule computes them. `observed-later.json` still differs from `three-node.json` in `observed_at` alone (`TestObservedLaterDiffersOnlyInObservedAt`). Under `testdata/ctm/defects/`: remove `iftype-subinterface.json`, `iftype-undeclared.json`, `iftype-unimplemented.json`, `link-endpoint-loopback.json`, `mgmt-only-loopback.json` and `parent-missing.json`, and move every other defect to `2`, each still failing by the rule it names alone.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. Converted by a script from each `1` fixture, then reviewed.
    - **The artifacts**: `three-node.json`, `observed-later.json`, `mixed.json` and the shuffled copies carry research §5.1's six documents, their MD5s checked against the text.
    - **The other fixtures keep their artifacts.** That includes lossy's illustrative ones, which still name `Loopback0`. A name the CTM holds no interface for draws no warning.
    - **The shuffled copies** list the fidelity rows in reverse, so that `Normalize`'s sort is tested too.
    - **Packages**: `cisco_iol` (`five.json`) and `acme_os` (`platform-unsupported.json`) stay unsupported.
    - **Two defects changed what they carry, for review**:
      - `five.json` lost its two iftype defects. In their place it carries an unlinked `n1:Ethernet99` (`interface.rule.unmatched`) and a link `n3:ethernet-1/1|n3:ethernet-1/2` (`link.endpoints.same_device`). It still holds five defects, five findings.
      - `required-missing.json` blanks `envelope.schema_hash` where it blanked `n3`'s nos. An empty package is `platform.unsupported` by T020's text, and it is malformed against CTM `2`'s `^[a-z0-9_]+$`, while every other defect stays well-formed against the contract.

- [X] T020 `internal/validate` (data-model §2, "Validation"; R-09).
  - **Removed**: the rules `interface.iftype.unimplemented`, `interface.mgmt_only.iftype`, `interface.parent.missing` and `link.endpoint.iftype`, their cases in `rules_test.go` and `defects_test.go`, and their four constants from `internal/findings/finding.go` and `finding_test.go`'s tables (their last users).
  - **Required in the envelope** (`data.required.missing`): `branch`, `observed_at`, `schema_hash`, `scope`, `mapping.reader`, `mapping.model` and `mapping.version`. `contract_version` is no longer required.
  - **The platform**: `platform.package` must be non-empty and in the registry by `psp.Registry.LookupID`; otherwise `platform.unsupported`, naming the package and the registry's ids.
  - **Unchanged**: names unique, links with two ends on distinct devices each naming an interface of a device in the CTM, and the artifact rules.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. The four rules, their constants, `finding_test.go`'s rows and their test cases are gone.
    - **The envelope** requires `branch`, `observed_at`, `schema_hash`, `scope` and the three `mapping` fields, each named as `envelope.<field>`.
    - **The package**: one the registry lacks, or none, is `platform.unsupported`, naming it and `psp.Registry.IDs()` (new: the sorted package ids). For example: `no support package "acme_os"; supported: [arista_eos nokia_srlinux]`, or `device names no support package; supported: […]`. `compiler.UnsupportedPackage` words it for both callers.
    - **Tests**: `TestPlatformUnsupportedNamesThePackageAndTheRegistry`. The defect table loses six rows, and `version-1.json` is covered by `ctm`'s test.

- [X] T021 `internal/compiler` (R-07, R-09; data-model §3).
  - **Lookup**: the device's package by `reg.LookupID(platform.package)`, with `Lookup(nos)` gone from product code (grep `internal/` and `cmd/` outside tests).
  - **The survey**: `SurveyDevice` keeps two arms, the `mgmt_only` arm (a second one omitted as `omit.mgmt.extra`) and the data rules. The loopback arm, the `default` arm and `DeviceSurvey.Err` go.
  - **The manifest**: `MappingRow` loses `Iftype`. `Provenance{Branch, At, SchemaHash, Scope, Mapping}` is filled from the envelope. `Fidelity.Read []ctm.FidelityRow` is the envelope's list copied verbatim, `[]` never `null`. `BundleVersion = "5"`.
  - **Unchanged**: the breakout rule, sharing, collisions and `ArtifactNames`.
  - **Tests**: `TestEveryInterfaceIsAPort` (a CTM whose every non-management interface becomes a port, cabled when linked and configured-not-cabled otherwise); the survey tests without the loopback arm; `TestManifestCopiesTheFidelityList` (a CTM with an invented row, whose text appears nowhere in `internal/compiler`, reaches `fidelity.read` unchanged; grep the package's non-test files for each of [contracts/mapping.md](contracts/mapping.md) §5's reason texts and find none); `TestCompilerNamesNoPlatform` and `TestCompilerIsPure` hold; `refusal_parity_test.go` keeps validation's and the compiler's wording alike. Fix `mapping_test.go`, `eos_test.go`, `fidelity_test.go`, `artifact_names_test.go` and `refusal_parity_test.go` where they name the removed constants. Run the golden tests only after T024.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. The changes are as the task lists them.
    - **The survey** keeps a two-arm `switch`: `mgmt_only`, and `default`, the data port.
    - **The manifest**: `nodes[].platform` takes the package's `nos`, as R-08 says. `Fidelity.Read` is last in the block.
    - **New tests**: `TestEveryInterfaceIsAPort` (`mapping_test.go`) and `TestManifestCopiesTheFidelityList` (`fidelity_test.go`), and a mapping case: `lo0` is a port, so `interface.rule.unmatched`.
    - **`TestNothingLossyStillCarriesBothFields`** moved to `two-mgmt.json`. No three-node row is portless now, and a row with no port is what gives a `null` node name. It also holds `fidelity.read` required.
    - **`Lookup(nos)` left `compiler`, `validate` and the worker's start-up report**, which now enumerates `IDs()`. It remains in two places, both bridges: the generics reader's projection (T023, until T039) and `stages/stale.go`, whose stamps carry the generics' nos (`DeviceStamps.NOS`, until T049).

- [X] T022 Manifest `5` ([contracts/formats.md](contracts/formats.md) "Bundle manifest 5"). Copy the current `contracts/manifest.schema.json` unchanged to `internal/bundle/testdata/contracts/017-dcim-reader/manifest.schema.json` (the frozen `4`). Then move `contracts/manifest.schema.json` to `$id …/contracts/manifest/v5` and `bundle_version` `"5"`:
  - `provenance{branch, at?, schema_hash, scope, mapping{reader, model, version}}`, with `contract_version` gone;
  - `mapping[]` rows without `iftype`;
  - `fidelity.read`, the CTM's fidelity row shape, required.

  In `internal/bundle/verify.go`, accept `5` alone. A `4` is refused as `bundle.version.unsupported`, naming both. Test it in `verify_test.go` with a `4` manifest that is valid against the frozen copy. `internal/compiler/contract_test.go`'s manifest tests run against the new schema.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. The `4` is frozen at `internal/bundle/testdata/contracts/017-dcim-reader/manifest.schema.json`. `contracts/manifest.schema.json` is `5`: `provenance{branch, at?, schema_hash, scope, mapping}`, rows without `iftype`, and `fidelity.read` required, its items the CTM's row shape.
    - **For review**: the `$id` keeps its path segment, `…/contracts/bundle-manifest/v5`, beside `v4`'s `bundle-manifest/v4`. The task wrote `manifest/v5`.
    - **`bundle.Verify` accepts `5` alone.** `internal/bundle/testdata/three-node-4.manifest.json` is the three-node golden's last `4` manifest. The new subtest validates it against the frozen copy, then expects `bundle.version.unsupported` naming `"4"` and `"5"`. `4` joined the earlier-format loop, and the later format is now `6`.

- [X] T023 Bridge the old reader over CTM `2`, for two runs (this file's first ordering). Change the least code that keeps `internal/intent`, `internal/stage`, `internal/server` and `internal/cli` compiling, and their tier-1 tests green and truthful:
  - `internal/intent/project.go` stops writing the removed fields, and skips the interfaces the generics type as loopback or subinterface, since CTM `2` has none.
  - `platform.package` is the package the registry finds for the generics' platform `nos`.
  - The envelope's `scope` is `tag:` + `Config.Scope`, and its `mapping` is `{reader: "infrahub-generics", model: "fylgja-generics", version: "0.2"}`, which is what it reads. Its `fidelity` is `[]`.
  - `stage.CheckContract` stays (T042 removes it).
  - Mark the bridge with a comment naming T039. Tests that pin a read's CTM, manifest, record or bundle id move with T019's fixtures and T024's ids.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. The bridge, marked `017's T023` in each place.
    - **The read**: `projectDevice` writes `platform.package`, the package `reg.Lookup(nos)` finds, else the nos verbatim, so that validation's `platform.unsupported` names what the branch declared. Such a CTM is refused and never written.
    - **`projectInterface` skips every interface not typed `physical`.** That includes `svi`, which CTM `2` has no place for either, beside the loopback and the subinterface the task names.
    - **The envelope**: `scope` is `tag:` + `Config.Scope`, `mapping` is `{infrahub-generics, fylgja-generics, <the contract version conformance checked>}`, and `fidelity` is `[]`.
    - **The stamps** keep the generics' `nos` (`DeviceStamps.NOS`) for `stages/stale.go` until T049.
    - **`stage.CheckContract` stays, returning nothing.** A CTM `2` declares no contract version, and `Unmarshal` refuses any other `ctm_version`.
    - **Two more bridges the tree needed, for review**:
      - `twin step` reads under the server's `DefaultScope`, where it read under none (`internal/server/step.go`, until T046). An empty scope would have written `tag:` into the envelope and moved the step's bundle off the plan's.
      - The worker writes a `twin.json` `7` provenance without `contract_version`'s value (`lab.recordProvenance`, until T025), since `7` has no place for the scope and the mapping.
    - **Tests**: both fake Infrahubs serve each CTM `2` fixture back in the generics' shapes, every interface `physical`, the package mapped back to vendor and nos.
      - `internal/cli`'s `bridged()` and `bridgedFixtureBundleID` say what the harness's read of a fixture is during the bridge: the generics' mapping and no fidelity row. T043 removes both.
      - `TestContractVersionMismatchIsReportedAlone` and `TestContractVersionIsCheckedBeforeValidation` became `TestAnotherCTMVersionIsRefusedBeforeValidation` (exit 2, `operation.failed`, until T042 files `ctm.version.unsupported`).
      - Tier-2 files changed only to compile: `read_contract_test.go`, `artifact_contract_test.go`, `mixed_contract_test.go`, `defects_contract_test.go`. T044 rewrites them.

- [X] T024 Re-baseline the goldens (FR-032; R-07): after T017–T023, run `go test ./internal/compiler -update`. Review the diff: every manifest's provenance, mapping rows and `fidelity.read`; every bootstrap that lost `lo0`; every artifact. Update every test that pins one of the three old ids (`23f86a26…`, `5773b6bb…`, `391bcb96…`; grep `*.go` and `scripts/`) to the new ids. Commit T017–T023 first, then the goldens and the ids alone, in a commit of their own (`test(compiler): re-baseline the goldens for CTM 2 and manifest 5`), whose body names the three new ids. Write the three new ids in this task's note; `CLAUDE.md` takes them at T071. The loop stops here for the golden diff's review.
  - *2026-10-25 22:40Z, at `f3699d0`, Run 6 of the converge loop:* done. `go test ./internal/compiler -update`, then the old ids replaced in `*.go` (`scripts/` held none). The new ids:
    - three-node **`43d917158d2b601cd2cdeb6aafd56d367224d757c4ce3f67fdf3c206e2c5a386`**
    - lossy **`4213b3cfd532f896d476c67c21f54e5375effdbec18f4376360471fd03f50b03`**
    - mixed **`ecb665f58ffc9882024a06e29b01e681ee38ce40f55b76994d470fe3272a2aec`**

    **The diff, reviewed**:
    - Each manifest is `5`: the provenance's `scope` and `mapping` in place of `contract_version`, no `iftype`, and no loopback row (three per golden). `fidelity.read` holds mapping.md §5's three rows.
    - The three-node and mixed artifacts are T016's predicted bytes, sizes and checksums. Each lost its loopback stanza, and its header's second line moved.
    - Lossy's artifacts did not move.
    - **No bootstrap and no topology moved**: a bootstrap renders cabled ports alone and never held `lo0`.

    **Committed in three, for review**: T017–T023 first (`3cc4a45`), the goldens with the id pins alone second (`bf15328`, `test(compiler): re-baseline …`), and this file third. Golden-derived pins that are not ids moved with T019's fixtures in the first commit: the n1 checksum and n3 size in `bundle`'s tests, the fixture's artifact checksums and 707-byte sizes in `internal/cli`, and the interface counts in the read summaries (12 to 9, 19 to 16). The first commit's tier 1 fails wherever it compares with a golden or its id, which the second commit moves.

    **Not moved, for T034**: `docs/diagrams/topologies.md` still names the three old ids. `make diagrams` regenerates it, and it needs Docker.

  *Run 6's checkpoint, 22:45Z*: `make build` static; `make test` uncached 38.6 s wall (load average 1.8 before, 3.1 after; 41.8 s at 4.5 to 6.6 on an earlier pass); `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean. T017–T024 name no tier-2 test, so none was run, and Infrahub was not touched. No twin was booted. The worker and the server were not touched, and both `/proc/<pid>/exe` still read `(deleted)`; T059 restarts them.

- [X] T025 `twin.json` `8` ([contracts/formats.md](contracts/formats.md) "`twin.json` 8").
  - **Freeze**: copy the current `contracts/twin.schema.json` unchanged to `internal/lab/testdata/contracts/015-proposed-change-rehearsal/twin.schema.json`, the frozen `7`.
  - **The schema**: `contracts/twin.schema.json` moves to `$id …/contracts/twin/v8`, with `twin_version` `"8"` and `provenance` shaped as the manifest's.
  - **The types**: `internal/lab/wire/types.go`'s `Provenance` mirrors `compiler.Provenance` (`Scope`, `Mapping`; no `ContractVersion`), and `internal/lab/twin.go`'s `TwinVersion` becomes `"8"`. A `7` record decodes with no scope.
  - **Tests in `internal/lab/twin_test.go`**: `TestRecord8` (a create's record names its scope and mapping, valid against the contract) and `TestRecord7ReadsWithNoScope` (against the frozen copy). Rename the `…Version7…` tests to `…Version8…`, and make the tests that rewrite a record as an older worker wrote it drop `scope` and `mapping`.
  - **The script**: set `scripts/e2e.sh`'s expected record version to `8`, so that `TestE2EScriptExpectsTheRecordsVersion` passes. The rest of the script is T054's.
  - **The count**: set `frozenContractCopies` in `internal/findings/frozen_contracts_test.go` to the number its glob finds after T017, T022 and this task each add one (30 → 33).
  - *2026-10-26 00:10Z, at `5d8112e`, Run 7 of the converge loop:* done.
    - **The contract**: the `7` is frozen byte for byte. `contracts/twin.schema.json` is `…/contracts/twin/v8`, with a 017 sentence in its title and description. Its `provenance` is the manifest's block copied whole: `scope` matching `^tag:\S+$`, and `mapping{reader, model, version}`, all required.
    - **The types**: `wire.Provenance{Branch, At, SchemaHash, Scope, Mapping}`, with `wire.Mapping{Reader, Model, Version}` as its own mirror, since `wire` imports neither `compiler` nor `ctm`. `lab.recordProvenance` copies the manifest's block whole, so the bridge's empty provenance (T023) is gone. A `7` record decodes leniently, as every earlier one did: `contract_version` is ignored, and `Scope` and `Mapping` read empty.
    - **Two refusals the task does not name, for review**:
      - `NewRecord` refuses a provenance naming no scope, or a mapping with an empty field, as it refuses what the contract would not accept.
      - `NewStepRecord` refuses a diverged step from a record of `7` or earlier. Such a step keeps the previous record's provenance, which has no scope, and `8` cannot hold that. A stepped step from one takes the target's provenance and is an `8`.
    - **Tests**: `TestRecord8` (a create's, a stepped and a diverged step's provenance; the contract refusing each half left out or malformed, `contract_version` and `twin_version 7`; `NewRecord`'s refusal). `TestRecord7ReadsWithNoScope` (a rehearsal's baseline and a step, as a 015 worker wrote them, against the frozen `7`, read with no scope or mapping and the rehearsal kept; the frozen `7` refuses an `8`). `TestCreateWritesVersion8`, `TestVersion8RecordCarriesEachWait` and `TestVersion8RecordRoundTrips` are renamed. **For review**: `TestRecord7` is renamed `TestRecordNamesItsRehearsal`, since its subject is the rehearsal key, which `8` keeps, and beside `TestRecord7ReadsWithNoScope` its old name would mislead.
    - **The rewrites**: every test that rewrites a record as an older worker wrote it drops `scope` and `mapping` and puts `contract_version` back (`contractProvenance`, in `lab` and `cli`), since the frozen `2`–`7` contracts require it. `TestNewStepRecordFromAVersion3Record`: stepped writes an `8` with the target's provenance; diverged is refused.
    - **The rest**: test fixtures name `tag:fylgja` and the DCIM mapping (`dcimMapping`, one per test package) in place of `ContractVersion`. `scripts/e2e.sh`'s four `.twin_version` expectations read `8`. `frozenContractCopies` is 33, and the glob finds 33.

- [X] T026 The record's provenance in the documents ([contracts/formats.md](contracts/formats.md) "The findings blocks"; R-07).
  - **Types**: `findings.ShowRecord` carries `Scope` and `Mapping` in place of `ContractVersion` (`internal/findings/render.go`), the one document type that carries it. The verify document's `twin` block and the step's two sides name the bundle and the stage, never the record's provenance, and are unchanged; the scope of a step's or a verify's read is the document's `subject.scope`.
  - **Schemas**: `contracts/show.schema.json` moves with it; `verify.schema.json` and `step.schema.json` hold no `contract_version` and do not move.
  - **`twin show`**: the record line reads `record: branch b at …, bundle_id …, schema …, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9`, and for a `7` record `…, scope unknown (record 7)` (built in `internal/server/show.go` and wherever the text line is rendered).
  - **`twin step`** refuses a `7` record as `step.twin.unsteppable`, naming the version (`the twin was created from a record version this build no longer reads (twin.json 7); fylgja twin destroy clears it`), as it refuses a `5` (`internal/server/step.go`).
  - **Other commands on a `7` record**: `twin destroy` clears it, and `twin rehearse` still reclaims one that names a dead rehearsal.
  - **Tests**: `internal/cli/show_test.go` (both lines); `internal/server/step_test.go` (the `7` refusal); the frozen M-era contracts still accept a document without `scope`.
  - *2026-10-26 00:10Z, at `5d8112e`, Run 7 of the converge loop:* done.
    - **The document**: `findings.ShowRecord` carries `Scope` (`omitempty`) and `Mapping *ShowMapping` (`omitempty`) in place of `ContractVersion`. Both are present for an `8` record and absent for a `7` or earlier one, which the server tells by the record's version. `contracts/show.schema.json`'s `record` loses `contract_version` from `required` and `properties`, and gains `scope` (`^tag:\S+$`) and `mapping` as the manifest gives them. Each requires the other (`dependentRequired`), and the description has a 017 sentence. `verify.schema.json` and `step.schema.json` did not move.
    - **`twin show`**: the record line ends `…, schema <hash>, scope tag:fylgja, read by <reader> from <model>@<version>` (`provenanceClause`, `internal/server/show.go`, the one place it is built). Any record before `8` reads `…, scope unknown (record <version>)`, `2` to `7` alike. During the bridge a fresh record's line truthfully says `read by infrahub-generics from fylgja-generics@0.2`. formats.md also names `twin create`'s record line, but this build's `twin create` prints none, so only `twin show`'s moved.
    - **`twin step`**: `stepScopeUnknown` refuses a stage twin whose record is `7` or earlier as `step.twin.unsteppable`, at `resolve`, object the record's bundle: `the twin was created from a record version this build no longer reads (twin.json 7); fylgja twin destroy clears it`. A `6` is refused the same way, naming `6`, since it names no scope either.
    - **One departure, for review**: the refusal is in `internal/server/step.go`, after `provision.Ineligible` and before the proposed change is asked for, not in `Ineligible` itself. The run's second lock calls `Ineligible` on the records in `step-cancelled`, `step-diverged` and `step-wait-cancelled`'s recorded histories, which are `4` and `5` records carrying stages. There it would refuse them, and those histories must replay unchanged.
      - What this ordering means: a diverged `7` is still refused as diverged, and a branch or bundle twin of `7` as not from a stage, as a `5`'s are.
      - Its comment says a worker of this build writes `8`, so only a record changed under the run reaches the lock. `NewStepRecord`'s refusal (T025) covers that case.
    - **Destroy and rehearse on a `7` record**: `twin destroy` reads neither the record's version nor its provenance, since teardown is planned from the staged manifest or from inspect. `TestRehearseReclaimsADeadRehearsalsTwin` now runs over an `8` and a `7` record of a dead rehearsal, and both are reclaimed.
    - **Tests**:
      - `TestShowRecordNamesItsScope` (`cli`): both lines; the JSON scope and mapping present for an `8` and absent for a `7`; the current contract; the rehearsal kept.
      - `TestStepRefusesARecordThatNamesNoScope` (`server`).
      - Rows `a record of twin.json 7` and `… 6` in `TestStepRefusedBeforeAnyConnection`: refused through the harness with nothing asked of Infrahub and the service never dialled.
      - `TestShowRecordCarriesTheRecordsProvenance` (`findings`): the contract accepts both shapes and refuses either half alone, a scope that is not a tag, a mapping missing a field, and `contract_version`.
      - Every record-line pin in `show_test.go` moved, and the pins of records before `8` read `scope unknown (record N)`.
    - **The frozen M-era contracts**: each still accepts this build's documents once a document is put back as its milestone wrote it.
      - In `findings`, `asEarlier` always applies `drop017ShowProvenance` (the record's `scope` and `mapping` out, `contract_version` back), since every schema it serves predates 017. `TestAnM7DocumentIsUnchanged` holds M7 to that projection and the current contract to the document as built.
      - In `cli`, `asEarlierContract` replaces T014's `withoutScope`. It validates whole against the current contract whatever 017 added, then drops the subject's scope and puts the record's provenance back the same way.
    - **Not done here**: `twin step` still reads under the server's default (T046), and its comment now says so.

  *Run 7's checkpoint, 00:10Z*:
  - **Gates**: `make build` static. `make test` uncached took 43.4 s wall with the changed packages compiled cold (load average 1.9 before, 3.6 after), then 34.0 s warm (3.4, 3.3), under 45 s. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` and `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean. No golden moved in this run.
  - **Tier 2**: T025 and T026 name no tier-2 test, so none was run, and Infrahub was not touched.
  - **The host**: no twin was booted. The worker (pid 2314364) and the server (pid 2314366), restarted since Run 6, were not touched; after this run's build both `/proc/<pid>/exe` read `(deleted)`.
  - **The C4 model** needs no redraw: no package gained an import.

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

- [X] T027 [P] [US6] Vendor the library (R-12; FR-035). In a new empty directory under the scratchpad, fetch `opsmill/schema-library` at `26336e9026dff1907f2c58e81dd6ae7b5c3f763e` (a shallow clone, or `raw.githubusercontent.com/opsmill/schema-library/<sha>/<path>`). Copy byte for byte to `schema/dcim/`: `base/dcim.yml` → `dcim.yml`, `base/ipam.yml` → `ipam.yml`, `base/location.yml` → `location.yml`, `base/organization.yml` → `organization.yml`, `extensions/cable/cable.yml` → `cable.yml`, `extensions/location_minimal/location_minimal.yml` → `location_minimal.yml`, and `LICENSE.txt`. Check each SHA-256 against research §1.2's prefixes (`81df2eb8…`, `6d31dc03…`, `afef7a77…`, `082e8536…`, `3196073c…`, `cf148227…`, `71d4aed1…`), and stop if any differs. Never format them. Write `schema/dcim/README.md`: the repository and the full commit, a table of each file's library path, vendored name and full SHA-256, the Apache 2.0 licence, that `-prepare-main` loads them in one request on an empty `main` alone (R-13), and that they are never reformatted.
  - *2026-10-26 01:20Z, at `f257a0c`, Run 8 of the converge loop:* done. A shallow fetch of `opsmill/schema-library` at `26336e9026dff1907f2c58e81dd6ae7b5c3f763e` (the merge of PR #98, 2026-10-09), in an empty scratchpad directory. The seven files were copied byte for byte under their library names, and each SHA-256 matches research §1.2's prefix: `dcim.yml` `81df2eb8…`, `ipam.yml` `6d31dc03…`, `location.yml` `afef7a77…`, `organization.yml` `082e8536…`, `cable.yml` `3196073c…`, `location_minimal.yml` `cf148227…`, `LICENSE.txt` `71d4aed1…`. None was formatted. `schema/dcim/README.md` names the repository and the full commit, and tables each file's library path, vendored name and full SHA-256. It also covers the Apache 2.0 licence (the library has no `NOTICE` file), that the files are never reformatted, and R-13's load: one request, on an empty `main` alone. **For review**: the README states R-13's gate, which `-prepare-main` gains at T031; until then it loads unconditionally (T028's note).

- [X] T028 [US6] After T002 and T027. In `embed.go`, embed `schema/dcim/*.yml` beside `schema/*.yaml`. Add `TestVendoredLibraryIsThePinnedCommit` in `embed_test.go`: each embedded file's SHA-256 equals the README's table, and the README names `26336e9026dff1907f2c58e81dd6ae7b5c3f763e`. Remove `schema/fylgja-generics.yaml` and `schema/reference.yaml`; `schema/fylgja-stage.yaml` stays. In `internal/testsupport/infrahub.go`, `LoadSchema` loads `schema/dcim/*.yml` in one request, then `schema/*.yaml` (the stage kind) in a second, and waits until `DcimDeviceCreate` and `FylgjaStageCreate` are mutations (data-model §11). `-schema-only` on a throwaway branch loads both.
  - *2026-10-26 01:20Z, Run 8 of the converge loop:* done.
    - **The embed**: `embed.go` embeds `schema/dcim/*.yml` beside `schema/*.yaml`, and its doc comment names the library in place of the generics. **For review**: it embeds `schema/dcim/LICENSE.txt` too, so that the binary carries the licence of the files it embeds.
    - **`TestVendoredLibraryIsThePinnedCommit`**: the README names the full commit; every file the binary embeds from `schema/dcim/` has the SHA-256 the README's table gives it; the table names every embedded file and nothing else (seven: the six and the licence); and each row keeps the library's file name. A byte appended to `cable.yml` fails it naming both sums. `TestTheStageKindIsEmbedded` now holds `schema/*.yaml` to the stage kind alone.
    - **Removed**: `schema/fylgja-generics.yaml` and `schema/reference.yaml`. `schema/fylgja-stage.yaml` stays. `schema/README.md` still describes the two removed files until T069 rewrites it. One link broke, in `specs/016-probes/brief.md`'s reading list; it now names the file as removed at 017 (`make linkcheck` clean), for 016's re-read.
    - **`LoadSchema(branch, schemaDir)`** keeps its signature. It loads `schemaDir/dcim/*.yml` in one request, then `schemaDir/*.yaml` in a second. It waits for the `Create` mutation of every node the loaded files define and do not remove (`state: absent`), `DcimDeviceCreate` and `FylgjaStageCreate` among them, and on a timeout names the ones still missing. A directory with no `dcim/` loads its own files alone, as `conformance_contract_test.go`'s additive load does.
    - **Verified live** (tier 2, read and throwaway writes only): `fylgja-fixture -branch fylgja-test-017-run8 -schema-only` loaded both in 49 s. The branch then exposed `DcimDeviceCreate`, `InterfacePhysicalCreate`, `DcimCableCreate`, `LocationSiteCreate` and `FylgjaStageCreate`, beside `main`'s `NetworkDeviceCreate`. Its hash read `7b029b0f…`, and `main`'s stayed `e43a1cde…`. The branch was deleted by T029's probe.
    - **What the operator needs to know**: `-prepare-main` calls `LoadSchema("main", …)`, so from this tree it loads the library onto `main`, ungated, until T031 adds the gate. Neither `-prepare-main` nor `scripts/bring-up.sh --part infrahub` should run on this host before T056.

- [X] T029 [US6] Load the `infrahub:infrahub-managing-objects` skill and read its SKILL.md before writing the seed, applying it where `CLAUDE.md` does not decide otherwise. Then rewrite `internal/testsupport/seed.go` in the library's kinds, as R-15 and data-model §12 give them:
  - **The objects**: `BuiltinTag fylgja`; `OrganizationManufacturer Nokia`; `DcimPlatform SR Linux` (manufacturer Nokia); `LocationRegion Lab region` → `LocationCountry Lab country` → `LocationMetro Lab metro` → `LocationSite lab`.
  - **The devices**: `n1`, `n2` and `n3`, each with `status active`, `location lab`, `platform SR Linux`, `tags [fylgja]` and `description` the marker. Each has the `InterfacePhysical`s `ethernet-1/1`, `ethernet-1/2` and `mgmt0` (`role management`), and no loopback.
  - **The cables**: three `DcimCable`s, each with `connected_endpoints` its two ports and `label` the link's canonical id. Then the group join and the generate, as today.
  - **The mixed seed**: it adds `Arista` and `EOS`, and the devices `s1`, `e1` and `e2` with their ports as data-model §12's table gives them, and three cables.
  - **The marker**: `MarkerDescription(branch)` = `FYLGJA-MARKER-<suffix>` by today's suffix rule. `MarkerPrefix` stays `FYLGJA-MARKER`.
  - **The helpers**: `EnsureTag`, `EnsureManufacturer`, `EnsurePlatform`, `EnsureSite` and `TagDevices`. `SeedThreeNode`'s idempotence reads `DcimDevice { count }`.
  - **The names**: keep exported names and signatures where the meaning holds, so every `contract`-tagged caller compiles. A renamed one moves at every caller in this task.
  - *2026-10-26 01:20Z, Run 8 of the converge loop:* done. The `infrahub:infrahub-managing-objects` skill was loaded and its SKILL.md, `rules/value-attributes.md` and `rules/children-hierarchy.md` read. The seed writes raw GraphQL creates, not object files. What applied: dropdowns by choice name (`management`, `active`, `disabled`); a location created under its parent; and writes on a branch, `main` only for D-054's window, as `CLAUDE.md` excepts.
    - **The seed** (`seed.go`): `SeedThreeNode` and `SeedMixed` write through one `writeTopology`, then join the group and generate as before. That covers the tag, the platforms (`EnsurePlatform`), the site (`EnsureSite`), and each device (`status active`, `location lab`, its platform, `tags [fylgja]`, `description` the marker). Each device gets its management port (`role management`), its data ports and no loopback. Each link becomes a cable `label`led with `ctm.CanonicalLinkID`. Idempotence reads `DcimDevice { count }`. The mixed seed is data-model §12's table.
    - **The marker**: `MarkerDescription(branch)`, `FYLGJA-MARKER-<suffix>` by today's rule; `MarkerPrefix` stays. `MarkerRole` is gone, moved at every caller (`internal/stage`'s two tier-2 files, and `internal/cli/marker_test.go`'s comment).
    - **The helpers**:
      - `EnsureTag(branch, name)` and `EnsureManufacturer(branch, name)`.
      - `EnsurePlatform(branch, manufacturer, name)`. An empty manufacturer is a platform with none. A platform of the name held under another manufacturer is refused, not reused, since a package matches the pair.
      - `EnsureSite(branch)`: `Lab region` → `Lab country` → `Lab metro` → `lab`.
      - `TagDevices(branch, tag, devices...)`, by `RelationshipAdd` on `tags`.
      - `FixtureTag`, `RoleManagement` and `StatusDisabled` as constants.
    - **The names that held** keep their signatures: `SeedThreeNode`, `SeedMixed`, `SeedThirdLink`, `SeedFourthNode`, `SeedMixedLink`, `DisablePort`, `DeleteLink` (the cable at the port, by `DcimCable(connected_endpoints__ids:)`), `DeviceNames`, and `AddInterface` (`proposed.go`).
    - **For review**:
      - `SeedFourthNode` gives n4 the peer's platform and site, where it counted the branch's platforms.
      - `SeedDefects`, its five defect constants, `SeedContractVersion` and `ContractVersion` are kept in the generics' kinds, moved whole to `internal/testsupport/generics.go`, whose header says why. The defect and conformance tier-2 tests that call them are T044's to rewrite or remove. They still work on a branch made from `main` until T056, since `main` holds the generics until then.
      - `LoadGenericsOnly` is removed: it had no caller, and its file is gone.
    - **Verified live** (tier 2), by a probe test that was not committed, on `fylgja-test-017-run8` and `fylgja-test-017-run8b`, both deleted at its end (`TestRun8Probe`, 499.7 s, pass):
      - the three-node writes: 3 devices, 9 ports, 3 cables with the three canonical labels and both ends, 1 tag, 1 platform under Nokia, 4 locations, no virtual interface;
      - n1 as R-15 gives it, its three ports `InterfacePhysical` with `mgmt0` alone `management`;
      - `EnsurePlatform` idempotent, refusing `nokia` / `SR Linux` naming both manufacturers, and writing `Orphan OS` with none;
      - the group join of three `DcimDevice`s;
      - `SetDeviceDescription`, `SetDeviceSerial` (`LAB-0001`) and `DisablePort` (`status disabled`) read back;
      - `AddInterface`, refused a second time;
      - `TagDevices` (n3 carries `fylgja` and `other`);
      - `DeleteLink` (2 cables, the port's `connector` null) and `DeviceNames`;
      - `SeedThirdLink`, `SeedFourthNode` (n4 on SR Linux at lab, tagged, `mgmt0` management, cabled `n2:ethernet-1/3|n4:ethernet-1/1`), `SeedMixed` (EOS under Arista with 2 devices, SR Linux under Nokia with 1) and `SeedMixedLink` (`e1:Ethernet3|s1:ethernet-1/3`), each refused a second time.
    - **What the probe showed of the generate**: every generate ends with each artifact `Error`, since the imported template (`3c3e79a`) reads `FylgjaDevice`. So no seed concludes, and no tier-2 test that seeds can pass on this host, until T058 imports this branch's template. This is R-14's order: `make infrahub-seed` waits for T060.

- [X] T030 [US6] The rest of test support in the library's kinds (R-15).
  - **`internal/testsupport/baseline.go`**: `SeedMain` and `ClearMain` write and clear the baseline (the tag, the manufacturer, the platform, the four locations, the three devices, their ports and cables, and the artifacts). Each refuses a `main` that holds any of those, as it refuses one holding the baseline today.
  - **The change helpers**: the add-link change (`ethernet-1/3` on n1 and n3, with their cable); the fourth node (n4 with `mgmt0` and `ethernet-1/1`, cabled to the peer's new `ethernet-1/3`); the mixed link (`s1:ethernet-1/3`, `e1:Ethernet3` and their cable); disable-port (`status: disabled`); and add-interface (an `InterfacePhysical`, uncabled).
  - **New**: `SetDeviceDescription` and `SetDeviceSerial`. `SetRole` and `SetSite` go.
  - **`proposed.go`**'s branch guards are unchanged.
  - **Gate**: `go vet -tags contract,fixture,e2e ./...` compiles every tagged file; tests whose assertions name the generics' kinds are rewritten at T044 and T051.
  - *2026-10-26 01:20Z, Run 8 of the converge loop:* done.
    - **`baseline.go`**: `SeedMainBaseline` and `ClearMainBaseline` keep their names; the task calls them `SeedMain` and `ClearMain`. They write and clear the baseline in the library's kinds.
      - **The seed** refuses a `main` holding any object of the baseline's kinds: `DcimCable`, `InterfacePhysical`, `DcimDevice`, `DcimPlatform`, `OrganizationManufacturer`, the four locations and `BuiltinTag`. Each is counted beside its generic (`DcimConnector`, `DcimInterface`, `DcimGenericDevice`, `OrganizationGeneric`, `LocationGeneric`).
      - **The clear** refuses while a test branch exists, as before. It also refuses anything beyond the baseline: a generic's count other than its concretes', a kind holding more than was read, any object not the baseline's by name, `<manufacturer>/<platform>`, `device:port` or canonical cable ends, and a device whose description is not the marker. Then it deletes in the order cables, ports, devices, platform, manufacturer, site, metro, country, region, tag, and last the artifacts Infrahub left.
      - **`ClearedBaseline`** counts cables, interfaces, devices, platforms, manufacturers, locations and tags (`Contracts` gone), and `-clear-main`'s line names each.
      - **For review**: the reads and the deletion take a branch (`clearBaseline(branch)`, `readBaseline(branch)`, `baselineCounts(branch)`). `ClearMainBaseline` runs the clear on `main` after its test-branch refusal, so the deletion was proved on a throwaway branch with no window open. On `main` today, which holds no library kind, both refuse at their first read.
    - **The change helpers** (in `seed.go`, T029's note): add-link, the fourth node, the mixed link, disable-port and add-interface. `SetDeviceDescription` and `SetDeviceSerial` are new. `SetDeviceRole` and `SetDeviceSite` are gone. `proposed.go`'s branch guards are unchanged.
    - **The callers moved, for review**: the role's callers call `SetDeviceDescription` and the site's `SetDeviceSerial`, with the values and the comment beside each call moved. The files are `internal/stage/artifact_contract_test.go`, `reproducibility_contract_test.go`, `internal/stages/stages_contract_test.go`, `internal/checks/checks_contract_test.go` and `internal/server/rehearse_contract_test.go`. Every stage label and assertion is untouched (T044, T051).
    - **One part of T031 done here, for review**: the fixture tool's `-set-description` replaces `-set-role` and `-set-site`, since their helpers went. The package comment names the library. T031 keeps the flags' help over the library's kinds and `-prepare-main`'s gate. `docs/development.md` still names the two old flags until T066.
    - **Verified live**: the probe (T029's note) cleared a three-node baseline written on `fylgja-test-017-run8b`: `{Cables:3 Interfaces:9 Devices:3 Platforms:1 Manufacturers:1 Locations:4 Tags:1}`, every kind 0 after. A second clear was refused (`holds no baseline`). On the changed branch the clear was refused, deleting nothing, and named the other tag, the two new cables, n4 and the six new ports. Its message then said `main` on any branch; it now names the branch.
    - **Gate**: `go vet -tags contract,fixture,e2e ./...` is clean.

  *Run 8's checkpoint, 01:20Z*:
  - **Gates**: `make build` static. `make test` uncached took 42.4 s wall (load average 3.3 before, 6.2 after), then 34.9 s on a second uncached pass (5.7, 5.5), under 45 s; `internal/cli` 30.8 s. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `make linkcheck` clean. No golden moved.
  - **Tier 2**: T028's schema load and T029's and T030's helpers were proved live on `fylgja-test-017-run8` and `-run8b` (T028–T030's notes). Both branches are deleted. `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`. Nothing was written to `main`.
  - **The host**: no twin was booted. The worker (pid 2314364) and the server (pid 2314366) were not touched; after this run's build both `/proc/<pid>/exe` read `(deleted)`.
  - **The C4 model** is not redrawn here: the schema and the artifacts repository are T034's.

- [X] T031 [US6] `cmd/fylgja-fixture/main.go` (FR-036–FR-038; R-13, R-15).
  - **Flags**: `-set-description <v>` sets every device's description on a throwaway branch, the artifact-only change, and replaces `-set-role` and `-set-site`. `-add-link`, `-add-fourth-node`, `-add-mixed-link`, `-disable-port`, `-add-interface`, `-seed-main` and `-clear-main` call T029's and T030's helpers. Each flag's help text names the library's kinds.
  - **`-prepare-main`'s gate**: before any write, it reads `GET /api/schema?branch=main` and lists which of the library's kinds `main` holds: every node and generic the six embedded files define, computed from the embedded YAML rather than a hand list.
  - None held: it loads the six files in one request, then the stage kind, the group and the registration as today, and prints `schema library loaded on main (6 files, opsmill/schema-library@26336e9)`.
  - Any held: it loads nothing and refuses with exit 1, before the group and the registration, with R-13's sentence: `main holds <n> of the schema library's kinds (<sorted names>): -prepare-main is the development host's and CI's tool, which loads the library on an empty main alone; a main that already holds the library is yours, and fylgja schema check says whether it is the one the reader reads`.
  - *2026-10-26 00:58Z, at `807ec5a`, Run 9 of the converge loop:* done.
    - **The gate**, in test support (`internal/testsupport/infrahub.go`):
      - `LibraryKinds(schemaDir)` names every node and generic the files under `schemaDir/dcim/` define, except one a `state: absent` removes, sorted: 27 at `26336e9` (research §5.2).
      - `KindsHeld(branch, kinds)` reads `GET /api/schema?branch=` and writes nothing.
      - `LoadLibrary(branch, schemaDir)` reads before any write. If the branch holds any of the kinds, it loads nothing and returns a `*LibraryHeldError`, whose sentence is R-13's word for word. If it holds none, it loads the six files in one request, waits for their `Create` mutations and returns how many files it loaded.
      - `LoadOwnSchema` loads the stage kind and says whether the schema hash moved.
      - `LoadSchema`, which loads a branch, keeps its behaviour and is not gated.
    - **`-prepare-main`** calls `LoadLibrary` on `main` first, so the refusal comes before the stage kind, the group and the registration, with exit 1. Otherwise it prints `schema library loaded on main (6 files, opsmill/schema-library@26336e9)`, built from `ctm.ModelSchemaLibrary` and `ctm.ModelVersion`. Then it prints `stage kind loaded on main` or `stage kind present`, then the group, the repository and the import as before.
    - **For review**: the kinds are computed from the files the gate guards, `-schema-dir`'s `dcim/`, not read from the binary's embed. With the repository's `schema/` they are the embedded files byte for byte (`TestVendoredLibraryIsThePinnedCommit`). A `-schema-dir` elsewhere is gated by what it would load.
    - **The flags**: the help text of `-schema-only`, `-add-link`, `-add-fourth-node`, `-add-mixed-link`, `-generate`, `-set-description`, `-disable-port`, `-add-interface`, `-mixed`, `-prepare-main`, `-seed-main` and `-clear-main` names the library's kinds. `-set-description` replaced `-set-role` and `-set-site` at Run 8 (T030's note), and every flag calls T029's and T030's helpers.
    - **Tests**: `internal/testsupport/library_test.go`, tagged `contract || fixture`, against an `httptest` Infrahub, needing none:
      - the 27 kinds;
      - a `state: absent` kind skipped, and a file beside `dcim/` not counted as the library's;
      - `KindsHeld`'s one read, and its refusal of a non-200 answer with the token redacted;
      - `LoadLibrary`'s refusal word for word, with no write;
      - its one load of six files on an empty `main`;
      - `LoadOwnSchema`'s rule on the hash.

      They run in tier 2 and by `go test -tags fixture ./internal/testsupport`, but not in `make test`, since the package is build-tagged.
    - **Verified live** (research §5.2): on the branch `fylgja-test-017-sdl` the gate refused, naming 27 kinds, and on `main` it found none. `-prepare-main` itself was not run: this host's `main` holds none of the library's kinds, so it would load the library, which is T056's to do.
    - **What the operator needs to know**: the gate refuses a `main` that holds the library, not one that holds the generics. So from this tree, `-prepare-main` and `scripts/bring-up.sh --part infrahub` would load the library onto today's `main` beside the generics, before R-14 step 1's two removal documents. Neither runs on this host before T056, which runs the documents first.
    - quickstart §2's expected second run now reads `main holds 27` (it said 21) and lists `DcimConnector` second, as the sorted names put it.

- [X] T032 [US6] `scripts/bring-up.sh`: the part that runs `-prepare-main` reads its exit 1 with R-13's sentence as `present`, and reports `main present (the library, the stage kind, the group, the repository)`. Any other failure stays a refusal. Every check of `main` or the fixture that names the generics' kinds (`/usr/bin/grep -n 'FylgjaDevice\|NetworkDevice\|FylgjaContract' scripts/bring-up.sh`) moves to the library's kinds. `shellcheck scripts/bring-up.sh` is clean. Write in this task's note how CI's runner path reads: fresh `main`, the library loaded, the merged template imported.
  - *2026-10-26 00:58Z, Run 9 of the converge loop:* done.
    - **The refusal read as present**: the part keeps the tool's exit status. An exit 1 whose output carries R-13's sentence (`library_held`) is a second run's answer. The script then reads `main` by name for the stage kind `FylgjaStage` (`/api/schema?branch=main`), the group `fylgja-devices` and the registration `fylgja` (`main_lacks`), and reports `main present (the library, the stage kind, the group, the repository)`. If any is missing it fails naming them, since `-prepare-main` writes nothing on a `main` that holds the library.
    - **For review**: the three reads are an addition. The refusal comes before the group and the registration, so without them the present line would claim what nothing had read. One such case: a first run that loaded the library and then failed its import wait.
    - **Exit 0 is always installed**: since the gate refuses a `main` that holds the library, a run that succeeds has loaded it. The line reads `(the library loaded; the stage kind, the group and the repository registered and imported)`. The relayed lines drop `go run`'s `exit status 1`. Any other failure is the refusal it was.
    - **The generics' kinds**: `fixture_state` reads `DcimDevice` in place of `FylgjaDevice`, which was the grep's two hits in one query. The grep now finds nothing.
    - **Checked**, read-only and with `local/.env` not loaded (`with_env` stubbed): `library_held` against two sample logs, a refusal and a missing-variable failure; `main_lacks` against today's `main` (nothing missing), and with three names that do not exist (all three named). The script itself was not run: it needs sudo, and its Infrahub part would run `-prepare-main` on this host's `main` (T056). `shellcheck scripts/bring-up.sh scripts/e2e.sh` is clean.
    - **CI's runner path**: the contract job runs on a push to `main`. It runs `scripts/bring-up.sh --part infrahub` on a fresh Infrahub whose `main` holds none of the library's kinds.
      - `-prepare-main` loads the six files in one request (`schema library loaded on main (6 files, opsmill/schema-library@26336e9)`), then the stage kind (`stage kind loaded on main`).
      - It creates the group, registers this repository at `ref main`, and waits for the import of `origin`'s `main`. Once 017 is merged and pushed (T057), that carries the template and query that read `DcimDevice`. The part reports `main installed`.
      - The fixture is absent, so `make infrahub-seed` seeds it in the library's kinds. Its generate renders through the merged template, and `fixture_state` counts three `DcimDevice` artifacts `Ready`.
      - The job runs on `main`'s pushes alone, so it first meets this tree merged, and never imports a template that reads `FylgjaDevice` over the library's kinds, under which every artifact would end `Error` (T029's note).

- [X] T033 [US6] The interim SDL and the typed client (R-14 step 5's interim). After T002 and T028. With `local/.env` loaded:
  - Run `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-017-sdl -schema-only`, then `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-017-sdl -sdl schema/infrahub.graphql`, keeping the file's header by hand as `make sdl`'s note says.
  - Capture `GET /api/schema?branch=fylgja-test-017-sdl`, trimmed with `jq` to the nodes `DcimDevice`, `DcimPlatform`, `OrganizationManufacturer`, `InterfacePhysical`, `InterfaceVirtual` and `DcimCable`, the generics `DcimGenericDevice`, `DcimInterface`, `DcimEndpoint`, `DcimConnector` and `CoreArtifactTarget`, and the top-level hash, into `internal/intent/testdata/schema-26336e9.json`. It is T036's fixture. Check it holds no token.
  - Dry-run `infrahub/queries/device_config.gql` against the branch (the skill's `deployment-gql-dry-run` rule), with `device: "none"`: no GraphQL error. Record it in research §5.2.
  - Delete the branch (`-branch fylgja-test-017-sdl -delete`).
  - Run `make generate`. The SDL carries the generics (from `main`) and the library both, so the old and the new operations both generate. Commit, then `go generate ./... && git diff --exit-code` is clean.
  - *2026-10-26 00:58Z, Run 9 of the converge loop:* done, as research §5.2 records. The session's environment held `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN`, so `local/.env` was not loaded.
    - **The branch**: `-schema-only` made `fylgja-test-017-sdl` from `main` and loaded the library and the stage kind in 39.5 s; its hash read `18e5f023…`.
    - **The SDL**: 2,255,885 bytes. Its header was written by hand and says it is the interim's: until `main` migrates, it is a throwaway branch's SDL with the library loaded, carrying the generics and the library both, and `make sdl` on the migrated `main` replaces it (T060).
    - **The schema document**: `internal/intent/testdata/schema-26336e9.json`, 110,497 bytes, holding the six nodes, the five generics and the hash, and no token. **For T036**: `CoreArtifactTarget`'s `used_by` names `NetworkDevice` beside `DcimDevice`, since the branch's `main` still held the reference kinds; and the hash is the throwaway branch's.
    - **The dry run**: no GraphQL error. The skill's `infrahubctl render … device=none` ran the query and stopped in the template at `edges[0]`, on a device the pipeline never asks for.
    - **The branch was deleted** at 00:52:58Z. `Branch` lists `main` and `fylgja-fixture` alone.
    - **The client**: `make generate` added 97 lines to `internal/intent/generated.go`, three types and no operation: the library's implementers of `CoreArtifactTarget` and `BuiltinIPAddress`. `go generate ./... && git diff --exit-code` is clean after the commit.

- [X] T034 [US6] Redraw for the schema and the template (`CLAUDE.md`: a changed component is redrawn in the same change). In `docs/c4/workspace.dsl`, the schema is the vendored library and the stage kind, and the artifacts repository renders from the library's kinds. Redraw `docs/diagrams/schema.md` from the six files' kinds the mapping reads (`DcimDevice`, `DcimPlatform`, `OrganizationManufacturer`, `InterfacePhysical`, `DcimCable`, the four generics), with `BuiltinTag` as the scope's tag and `FylgjaStage` with its proposed change, and its prose rewritten. Then run `make diagrams`; a second run changes nothing.
  - *2026-10-26 00:58Z, Run 9 of the converge loop:* done.
    - **`docs/c4/workspace.dsl`**: Infrahub holds intent in the schema library's DCIM, vendored at `26336e9` under `schema/dcim/`, beside Fylgja's one kind, the stage, and the Infrahub server's intent is in the library's DCIM. The artifacts repository renders from the library's kinds: the `DcimDevice` by name, its `DcimPlatform` and manufacturer, and its `InterfacePhysical` ports with their `DcimCable`s. The intent component's description is T045's.
    - **`docs/diagrams/schema.md`** is redrawn: the five kinds the mapping reads, the four generics, `BuiltinTag` carrying the scope, and `FylgjaStage` with `CoreProposedChange`. Each relationship is drawn as the conformance table checks it, on the kind the mapping reads and to the peer the table names, and "inherits" marks each `inherit_from`. The prose is rewritten for the mapping, the scope, the package's pair and the cable rule.
    - **`make diagrams`** (21.9 s) regenerated the Context, Containers and Deployment views (`.puml` and `.svg`); the component views did not move. A second run changed nothing.
    - **For review**: `docs/diagrams/topologies.md` moved too. Its three bundle ids are now the goldens' since T024 (`43d91715…`, `4213b3cf…`, `ecb665f5…`), which `scripts/diagrams.sh` computes from `testdata/golden/` and which no `make diagrams` had redrawn since. Nothing else in it moved.

  *Run 9's checkpoint, 00:58Z*:
  - **Gates**: `make build` static. `make test` uncached took 41.5 s wall with the regenerated client compiled cold (load average 2.1 before, 5.2 after; `internal/cli` 30.2 s), under 45 s. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...`, `shellcheck scripts/bring-up.sh scripts/e2e.sh` and `make linkcheck` clean. The gate's tagged tests pass (`go test -tags fixture ./internal/testsupport`). No golden moved.
  - **Tier 2**: T031's gate and T033's SDL, schema document and dry run were proved on `fylgja-test-017-sdl`, which is deleted (research §5.2). `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`. Nothing was written to `main`.
  - **The host**: no twin was booted. The worker (pid 2314364) and the server (pid 2314366) were not touched; both `/proc/<pid>/exe` read `(deleted)`.

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

- [X] T035 [US3] After T003 and T004. Create `internal/intent/mapping.go` (data-model §5): `KindTable{Kind, Attributes []AttributeWant{Name, Kind, Required bool, Choices []string}, Relationships []RelationshipWant{Name, Peer, Kind, Cardinality, Required bool}}`, `UsedByWant{Generic, Implementer}`, `LibraryTables` and `LibraryUsedBy`, holding exactly [contracts/mapping.md](contracts/mapping.md) §3's table:
  - `DcimDevice`: `name` Text, required; `tags` → `BuiltinTag`, Attribute, many, optional; `platform` → `DcimPlatform`, Attribute, one, optional; `interfaces` → `DcimInterface`, Component, many, optional; `artifacts` → `CoreArtifact`, Generic, many, optional.
  - `DcimPlatform`: `name` Text, required; `manufacturer` → `OrganizationManufacturer`, Attribute, one, optional.
  - `OrganizationManufacturer`: `name` Text, required.
  - `InterfacePhysical`: `name` Text, required; `role` Dropdown, optional, choices ⊇ {`management`}; `status` Dropdown, optional, choices ⊇ {`disabled`}; `device` → `DcimGenericDevice`, Parent, one, required; `connector` → `DcimConnector`, Attribute, one, optional.
  - `DcimCable`: `connected_endpoints` → `DcimEndpoint`, Attribute, many, optional.
  - `used_by`: `DcimGenericDevice` ⊇ {`DcimDevice`}, `DcimInterface` ⊇ {`InterfacePhysical`}, `DcimEndpoint` ⊇ {`InterfacePhysical`}, `DcimConnector` ⊇ {`DcimCable`}.

  Also add `LibraryModel = ctm.ModelSchemaLibrary` and `LibraryVersion = ctm.ModelVersion`. The package doc comment says this file is the one place that knows the library's kinds.
  - *2026-10-26 01:27Z, Run 10 of the converge loop:* done, as written. `KindTable.Fields()` names a kind's fields, attributes first, in the table's order: the `verified` block's `fields` and the success line's kinds come from it. The package doc comment (`client.go`) names `mapping.go`, and says the read is still the generics' until T039.

- [X] T036 [US3] Conformance (R-02; data-model §5).
  - **`SchemaInfo`** (`internal/intent/schemainfo.go`) gains `Nodes map[string]NodeSchema`, each with `Attributes map[string]AttributeSchema{Kind, Optional, Choices}` and `Relationships map[string]RelationshipSchema{Peer, Kind, Cardinality, Optional}` as the endpoint reports them (inherited members merged in), and keeps `Hash` and `UsedBy`.
  - **`CheckConformance`** (`conformance.go`) walks `LibraryTables` and `LibraryUsedBy` and files `schema.kind.missing` (object the kind), `schema.field.missing` (`<kind>.<field>`), `schema.field.mismatch` (`<kind>.<field>`; the property that differs, expected and found, such as `kind Text, found Number`, `cardinality one, found many`, `peer DcimPlatform, found NetPlatform`, or `optional false, found true`), `schema.choice.missing` (`<kind>.<field>`, the choice) and `schema.used_by.missing` (the generic, the implementer). Every message ends `as opsmill/schema-library@26336e9 has it`; every finding comes in one pass; nothing beyond the table is reported.
  - **`optional`** is compared as the endpoint reports it: a required member must read `optional: false`, and an optional one may read either.
  - **The results**: `Conformance{SchemaHash, Model, Version, Kinds []findings.KindFields}`; `findings.Verified{Model, Version, Kinds, Stages}` and `KindFields{Kind string; Fields []string}` in `internal/findings/render.go`, with `Verified()` in `summary.go`.
  - **Removed**: `schema.generic.unimplemented` and `schema.artifact_target.missing`, with their constants (their last users), and the generics-only code in `conformance.go`. The old `Fetch` keeps working off the new `Conformance`'s `SchemaHash` until T039.
  - **Tests** in `internal/intent/conformance_test.go`, over `httptest` serving `testdata/schema-26336e9.json` and mutations of it: a pass; `DcimCable` removed; `InterfacePhysical.role` removed; `DcimPlatform.name` as Number; `DcimDevice.platform` many and peered to `NetPlatform`; `DcimDevice.name` optional; `management` removed from `role`'s choices; `InterfacePhysical` removed from `DcimEndpoint.used_by`; all at once, giving every finding in one pass. Plus an extra kind and an extra field on `DcimDevice`, never reported. Each finding names `26336e9`.
  - *2026-10-26 01:27Z, Run 10 of the converge loop:* done.
    - **`SchemaInfo`** gains `Nodes`, each attribute's choices by name. `Kinds` went: `Nodes`' keys are the kinds, and its two users moved (`read_contract_test.go` reads `Nodes`).
    - **The messages**, each ending in the commit:
      - `the branch's schema has no kind DcimCable; the mapping reads it as opsmill/schema-library@26336e9 has it`;
      - `InterfacePhysical has no attribute role; …` (or `no relationship`);
      - `kind Text, found Number; …`;
      - `the dropdown has no choice management; …`;
      - `InterfacePhysical does not implement DcimEndpoint; the mapping reads InterfacePhysical through it as … has it`, and `the branch's schema has no generic DcimEndpoint; …` when the generic is absent.
    - **For review, three choices the text left open**:
      - One field is one finding: every property that differs is named in it, joined by `; ` (`peer DcimPlatform, found NetPlatform; cardinality one, found many`). The spec says one finding per kind or field.
      - A kind absent is named once. Neither its fields nor the generics it should implement are named beside it. So `DcimCable` removed is one finding even when, as Infrahub's endpoint would, it also leaves `DcimConnector`'s `used_by`.
      - "All at once" removes `disabled` from `status`, since `role` is removed in the same document. That gives seven findings, in the table's order and then the generics'.
    - **The bridge moved**: the generics' contract check left `conformance.go` for `project.go`'s `bridgeContract`, which the bridged `Fetch` runs before its first query.
      - A branch holding no `FylgjaContract` instance is still refused `contract.node.missing` with the same message, and one declaring another version `contract.version.mismatch`, with no CTM. A stage's branch point on a `main` with no network keeps its rule until T050.
      - The envelope's mapping version is `ctm.ContractVersion`, which is what the bridge reads. `stage.Read` returns before validation when `Fetch` refuses with no CTM; T040's completeness pass needs the same.
      - Unlike conformance before it, the bridge cannot see a branch with no `FylgjaContract` kind at all, whose query fails as a transport error. No such branch is read before T039.
    - **Removed**: `schema.generic.unimplemented`, `schema.artifact_target.missing`, `findings.GenericKinds`, the generics' conformance tests, and test support's `SeedContractVersion` (its last callers were two tier-2 tests: `TestContractVersionMismatchIsReportedAlone` and `TestDeviceKindWithoutTheArtifactTargetIsNamed`).
    - **Tests**: `TestConformanceOfTheLibrary`, `TestConformanceNamesWhatDiffers` (twelve cases: the task's eight, plus `connector` gone, `device` optional, `disabled` gone, `DcimEndpoint` gone and `InterfacePhysical` gone), `TestConformanceNamesEveryDifferenceInOnePass` and `TestConformanceIgnoresWhatTheTableDoesNotName`.
      - The last adds a choice and an implementer beyond the table, two optional fields read as required, and two fields the mapping does not read changed or removed.
      - `TestReadIsRefusedByConformance` (US3 scenario 4) and `TestBridgedReadRefusesABranchWithNoContract` cover the read.
      - `internal/provision`'s activity test now expects five `schema.kind.missing` on a schema holding nothing.
    - **Live** (research §5.3): on a throwaway branch holding the library, the untrimmed document (76 nodes) gave 0 findings. `fylgja-fixture` and `main` gave the five `schema.kind.missing` alone. The branch is deleted. **For the host**: a server built from this tree refuses every read of today's fixture and `main` until T056–T060. That is conformance working, and nothing live runs before Phase 11.

- [X] T037 [US3] `fylgja schema check` (FR-013; R-02, R-17).
  - **Success**: in `internal/server/schema.go`, the line is `conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, OrganizationManufacturer, InterfacePhysical, DcimCable`, then the stages line as today.
  - **`--json`**: `verified` is `{model, version, kinds: [{kind, fields: [...]}], stages}`, and `contracts/findings.schema.json`'s `verified` definition moves to it (`contract_version` and `generics` go).
  - **The harness's fake Infrahub** (`internal/cli/infrahub_test.go`) serves the trimmed schema document of T033 at `GET /api/schema`, beside its generics GraphQL answers, until T043.
  - **Tests**: `internal/server/schema_test.go` and `internal/cli/schema_test.go`: the success line and block valid against the schema, and a failing branch's findings, all in one document.
  - *2026-10-26 01:27Z, Run 10 of the converge loop:* done.
    - **The line**: `conformantLine` in `internal/server/schema.go`, from the `verified` block. The command's help text says what is checked against the pinned commit.
    - **The contract**: `contracts/findings.schema.json`'s `verified` requires `model`, `version` and `kinds` (at least one kind, each with at least one field). It refuses `contract_version` and `generics`, and its description names the two removals that formats.md accepts.
    - **For review**: `model` and `version` are non-empty strings, not the library's constants, so another reader's model fits the same block.
    - **Frozen schema**: M1's frozen findings schema still carries the old block, so `TestEveryOperationRendersAValidDocument`'s `schema check ok` case became a rejected check of the library's. The success is held to the current contract by `internal/findings/verified_test.go`'s `TestVerifiedIsTheMappingsTable`, which refuses seven malformed blocks.
    - **The harness**: its fake serves the trimmed document, with the fixture's hash, beside the generics' four rows. The bridged events reader still maps an event's kind through those rows (until T048), and T033's interim branch held both. `schemaMutations` serves a branch's document changed.
    - **Speed**: an unchanged document is encoded once per schema hash. Decoding and re-encoding it on every request had cost `internal/cli` about 5.5 s (36.1–36.7 s against 31.0 s at `74ed9b4`). Cached, the package took 31.3 s inside `make test`.
    - **Tests**: `TestConformantLineNamesTheCommitAndTheKinds` (server) and `TestCheckReportsTheMappingsTable` (cli). The cli test covers the exact line, the block's kinds and fields, both documents valid against the current contract, a diverged branch's two findings in one document with no step and nothing verified, and nothing asked of the default branch for it. `TestCheckNamesTheStageKind` now expects the new line.
    - **Tier 2, compile only (T044 rewrites them; they run at T062)**: `internal/cli/schema_contract_test.go` asserts the library's block on the fixture, and that a schema check issues no GraphQL at all. Its `TestSchemaCheckOnABranchWithoutAContractNode` went: a schema check no longer reads the contract node. `internal/intent/conformance_contract_test.go`'s fixture test asserts the library's model, version and kinds. Each passes once the fixture is re-seeded (T060).

  *Run 10's checkpoint, 01:30Z*:
  - **Gates**: `make build` static. `make test` uncached took 40.5 s wall (load average 2.8 before, 3.7 after; `internal/cli` 31.3 s), under 45 s. The run's first uncached pass took 48.9 s with the package at 36.6 s, before the harness cached its schema document (T037's note). `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` and `make linkcheck` clean; `go generate ./...` changes nothing. No golden moved.
  - **Tier 2**: no task of this run names a tier-2 test. Conformance was proved live on `fylgja-test-017-conf`, which is deleted (research §5.3). `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`. Nothing was written to `main`.
  - **The host**: no twin was booted. The worker (pid 2314364) and the server (pid 2314366) were not touched; both `/proc/<pid>/exe` read `(deleted)`.

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

- [X] T038 [US1] In `internal/intent/queries.graphql`, replace `ContractVersion`, the fragments `PlatformFields` and `InterfaceFields`, and the operations `Devices` and `Links` with [contracts/mapping.md](contracts/mapping.md) §2's two operations. Keep `ArtifactFields`.
  - `Devices($tag: String!, $limit: Int!, $offset: Int!)` is `DcimDevice(tags__name__value: $tag, limit, offset)`, selecting `id`, `name { value }`, `platform { node { name { value } manufacturer { node { name { value } } } } }` and `...ArtifactFields`. It selects no `interfaces`.
  - `Ports($devices: [ID], $limit: Int!, $offset: Int!)` is `InterfacePhysical(device__ids: $devices, limit, offset)`, selecting `id`, `name { value }`, `role { value }`, `status { value }`, `device { node { id } }` and `connector { node { id ... on DcimCable { label { value } } connected_endpoints { count edges { node { __typename id ... on InterfacePhysical { name { value } device { node { id } } } } } } } }`.
  - The stamps and the stage reader's operations are unchanged (T047).
  - Run `make generate`.
  - *2026-10-26 02:03Z, Run 11 of the converge loop:* done. `ContractVersion`, `PlatformFields`, `InterfaceFields`, `Devices` and `Links` are gone; `Devices` and `Ports` are as the task gives them, `ArtifactFields` kept, the stamps' operations unchanged. `make generate`, and a second `go generate ./...` changes nothing.
    - **For review, two genqlient directives the text did not name**:
      - The port's connector node is bound (`@genqlient(bind:)`) to `connectorNode` in `cable.go`, a plain struct. genqlient's generated decoder refuses any `__typename` its SDL does not name, so an end on an endpoint kind of the operator's own would have failed the whole read, where R-05 omits the cable `omit.cable.endpoint`. A connector that is not a `DcimCable` decodes too, and is judged like one. The selection is still checked against the SDL at generate.
      - The platform's and manufacturer's nodes are `pointer: true`, so a device with no platform, or a platform with no manufacturer, is told from one whose names are empty. A directive applies to every field on the line after it, so each node's selection spans lines.
    - **The read-only test** lists `Devices` and `Ports`. `TestQueryRootsAreFylgjaGenerics` admits the mapping's two roots, each only in its own operation, beside the Fylgja and Infrahub roots, until T052 replaces the three tests. The stamps still select the generics' roots until T047.

- [X] T039 [US1] [US2] The read (R-01, R-05, R-06; data-model §6), in `internal/intent/project.go` and a new `internal/intent/cable.go`. This replaces T023's bridge.
  - **`Fetch`** runs `Devices` with `Config.Scope`'s tag, paged by 100, every page at the read's `at` when one was given. Then it runs `Ports` once per page of 100 device ids, projects, judges the cables, writes the fidelity list, fetches the artifacts as today, relinks and normalizes.
  - **A port** is one per `InterfacePhysical`, by `name`. `mgmt_only` is `role == management`; `enabled` is `false` only when `status == disabled` (`null` and every other value is `true`).
  - **A cable** is judged once, by its id (`cableJudgement{id, label, ends []end{deviceID, deviceName, port, kind}}`), with the first reason that applies, in R-05's order:
    - `omit.cable.ends` when `count != 2`;
    - `omit.cable.endpoint` when an end's `__typename` is not `InterfacePhysical`;
    - `omit.cable.outside_scope` when an end's device id is not among the devices read.

    Each omission is an `info` finding beside the read: its object is the cable's `label`, or its id when it has none, and its message gives the reason text of [contracts/mapping.md](contracts/mapping.md) §4 (`other than two ends (<n>)`, `an end not on a physical port (<kind>)`, `an end outside the scope (<device>:<port>)`) and names every known end as `<device>:<port>`. Each is also a fidelity row `{omitted, <object>, DcimCable, <reason>}`. Any other cable is a link with today's canonical id, both ports `link`ed.
  - **The envelope** gets `scope` (`tag:<name>`), `mapping` (the three constants) and `fidelity` (the three fixed rows of T019 plus one per omitted cable, sorted).
  - *2026-10-26 02:03Z, Run 11 of the converge loop:* done, the bridge gone (`bridgeContract`, `ContractVersion`, `projectLink`, `relinkInterfaces`).
    - **`Fetch`** (`project.go`) runs `Devices` by `Config.Scope`'s tag, then `Ports` per hundred ids, each page of either paged by 100, every request at the read's `at`. It then runs completeness, projects, judges the cables and runs the artifact pass as before. A scope that selects nothing never sends `Ports`, whose filter would be empty.
    - **A port** is `role == management` and `status != disabled`, a null status enabled. Its link is set when its cable is judged one.
    - **`cable.go`**: `cableJudgement` keyed by the connector's id, judged in object order, R-05's three reasons in order.
      - The message is `cable <object> is omitted: <reason>; its ends are <device>:<port>, …`, every physical end listed, sorted. The row is `{omitted, <object>, DcimCable, <reason>}`.
      - **For review**: an end on a device outside the scope is named by its device's id, `18e1f1c5-…:port1`, since FR-002 has that device never read and `Ports` selects only its id. An end that is not a physical port has no name or device to list; its kind is in the reason.
      - **Added**: a cable that counts two ends and lists fewer (a null edge) is `omit.cable.ends`, `other than two ends (1 listed of 2)`, rather than a link with a missing end.
    - **The envelope**: `scope` `tag:<name>`, the mapping `infrahub-dcim`, `opsmill/schema-library`, `26336e9`, and `readFidelity()`'s three rows plus one per omitted cable, sorted by `Normalize`.
    - **Live** (research §5.6): on `fylgja-test-017-read`, holding the library and the three-node topology unrendered, plus an untagged `cs1` and two cables it cannot place, the read gave the fixture's three links and the two omissions with their rows. `cs1` was not read, and `tag:nothing` gave `scope.empty`. The branch is deleted.

- [X] T040 [US2] Completeness inside the scope (R-03; FR-014, FR-015), in `internal/intent/project.go` or a new `completeness.go`. Before any artifact is fetched, in one pass and with no CTM on any of them:
  - `scope.empty` (object the scope, the message naming the scope and the branch) when `Devices` answered 0.
  - `platform.missing` (object the device) for no platform, or a platform with no manufacturer. The message names what the device carries: `no platform`, or `platform "Orphan OS" with no manufacturer`.
  - `platform.unmatched` (object the device) when `reg.Match` finds nothing. The message is `manufacturer "nokia", platform "SR-Linux"; the packages match: nokia_srlinux [Nokia / SR Linux], arista_eos [Arista / EOS]`, every package and pair listed in a stable order.

  A device refused for its platform is not also refused for its artifact. The artifact rules are unchanged (FR-008).
  - *2026-10-26 02:03Z, Run 11 of the converge loop:* done, in `completeness.go`, after `Devices` and `Ports`, before the artifact pass.
    - **`scope.empty`** at the scope: `scope tag:nothing selects no device on branch b`, with ` at <at>` when pinned. It is filed alone, and no port is asked for.
    - **`platform.missing`**: `device n2 carries no platform; …`, and `device n3 carries platform "Orphan OS" with no manufacturer; …`.
    - **`platform.unmatched`**: `device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]`. For review: the stable order is package id order, which puts `arista_eos` first where the task's example lists `nokia_srlinux` first.
    - **One pass**: the devices are reported in name order. The artifact pass still runs over every device that has a package, so a refused read names their artifact faults beside the platform ones (FR-011); a device without a package is skipped by it. Then `Fetch` returns no CTM, so validation never runs on one.

- [X] T041 [US1] The read's report (R-17). `Counts.CablesOmitted` and `DevicesByPackage` reading `platform.package` live in `internal/intent/summary.go`. `intent read`'s summary line is `wrote <file>: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports; 1 cable omitted (branch b, scope tag:fylgja, schema 908871c3…)`, the omitted count only when non-zero, with a stage's `stage b/seeded: …` first as today (`internal/server/read.go` and where the line is rendered).
  - *2026-10-26 02:03Z, Run 11 of the converge loop:* done. `Counts.CablesOmitted` counts the envelope's `omitted` rows of source `DcimCable`; `DevicesByPackage`'s comment no longer garbles why it stands apart from `Counts`.
    - **The line**: `wrote ctm.json: …, 0 shared ports; 1 cable omitted (branch b, at T, scope tag:fylgja, schema …)`, with `2 cables omitted` for more than one and nothing when none. A stage's `stage b/l: ` stays first, before the reference.
    - **For review**: only `intent read`'s line names the scope (`scopedSubject`). The dry run's `read:` line and `stage plan`'s keep the reference and schema alone (`readSubject`), as no task moves them; T046 adds the scope to `stage plan`'s and `twin rehearse`'s headings.
    - **Tests**: `TestReadSummaryCountsTheLossyRecord` names the scope in its three lines and gains the one- and two-cable cases; `TestReadFromAStageIsThePinnedRead` names it too.

- [X] T042 [US1] `stage.Read` without the contract (`internal/stage/stage.go`). Remove `CheckContract`, and with it `contract.version.mismatch` and its constant (its last user). `twin compile` given a CTM of another version files `ctm.version.unsupported` (object the CTM file, exit 1, no step), naming both versions (`internal/server/compile.go`). Test it in `internal/server` or `internal/cli` with `testdata/ctm/defects/version-1.json`.
  - *2026-10-26 02:03Z, Run 11 of the converge loop:* done. `CheckContract` and `contract.version.mismatch` are gone, the constant and its row in `dataModelRules` with them, and `stage.Compile` validates first.
    - **The refusal**: `ctm.Unmarshal` returns a `*ctm.VersionError` (same text as before), and `twin compile` files it as `rejection ctm.version.unsupported <the --ctm path>: the CTM declares ctm_version "1"; this build reads "2", and nothing converts one`, exit 1, no step. Any other decoding failure stays `operation.failed`, exit 2.
    - **For review**: the run's Compile activity keeps `operation.failed` for a CTM it cannot read: it compiles only the CTM its own read wrote. `TestCreateReportsM1Findings` says so for `version-1.json`.
    - **Tests**: `TestAnotherCTMVersionIsRefusedBeforeValidation` (`internal/cli`, through the harness's server) asserts the finding whole. `TestVersion1IsRefused` asserts the typed error. `TestUnreadableCTMIsAnOperationalFailure`'s malformed file is a `"2"`, since a `"1"` is now the version's refusal. The pure rehearsal test that paired `contract.version.mismatch` with the branch point's refusal pairs `platform.missing` instead.

- [X] T043 [US1] [US2] The read's tier-1 tests (R-18; quickstart §1).
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
  - *2026-10-26 02:03Z, Run 11 of the converge loop:* done.
    - **The fakes**:
      - `internal/intent`'s fake moved to its own file, `infrahub_test.go`, and holds a branch in the library's terms: devices with tags and a pair, physical ports, virtual names it never serves, and cables. Its other-kind ends are written `<kind>#<id>`.
      - The harness's fake (`internal/cli/infrahub_test.go`) answers `Devices` by the tag `fylgja` and `Ports` by ids from each branch's CTM, each package's pair taken from the packages themselves.
      - Both dropped the generics' read answers and `contractless`. The harness keeps the generics' stamps answers and schema rows, which `IntentStamps` and the events still read until T047 and T048, but not the default branch's contract node.
      - `untagged` names a branch whose read answers no device; `emptyMain` is simply an empty CTM.
    - **`project_test.go`**:
      - `TestReadIsTheFixture`: the devices and links equal `three-node.json`'s; the envelope's branch, scope, mapping and rows are the fixture's; `DcimDevice(tags__name__value: $tag, …)` is sent with `tag` `fylgja` and no other argument; `Ports` is sent with the three ids.
      - `TestReadAsksForNothingOutsideItsScope` (US1 scenario 3) and `TestReadProjectsEachPort` (disabled, `maintenance`, a device with no port, `n2` under maintenance).
      - `TestReadRefusesEveryDeviceWithoutAPackage`: the three platform refusals and a fourth device's `artifact.missing` in one pass, no content fetched for the three.
      - `TestScopeSelectingNothingIsRefused`, and `TestReadPagesDevicesAndPorts` (150 devices, two pages of ports for the first hundred).
    - **`cable_test.go`**:
      - `TestCablesTheReadCannotPlace`: three ends, one end, outside, a `DcimConsolePort` end and a cable with no label, each finding and row exact, `CablesOmitted` 4.
      - `TestACableIsJudgedOnceByTheFirstReason`, `TestManagementCableReachesTheCTM` (FR-007) and the short listing's case.
    - **Moved**:
      - `TestReadRefusesEveryDeviceInOnePass` puts its intent fault in a cable with both ends on `n1` (`link.endpoints.same_device`), since a one-ended cable is now an omission. `TestBridgedReadRefusesABranchWithNoContract` went.
      - The harness's tests of a `main` holding no network, and of a branch whose devices are untagged, expect `scope.empty` at read: `stage plan`, `stage`, `twin step` and `twin rehearse`, their text included. `bridged()` and `bridgedFixtureBundleID` went.
      - The read predicates name `Devices` and `Ports`.
    - **For review, a bridge until T050**: `passedOver` (`internal/server/rehearse.go`) excuses `scope.empty` at read beside `contract.node.missing` at read. The new read refuses an empty `main` `scope.empty` where the generics' refused `contract.node.missing`, and T050 moves it to `resolve` and removes the old rule. `TestRehearsalStagesTakeTheBaselineRule` covers it.
    - **Tier 2, compile only** (T044 rewrites them; they run at T062): `read_contract_test.go` expects the library's mapping.

  *Run 11's checkpoint, 02:05Z*:
  - **Gates**: `make build` static. `make test` uncached took 42.5 s wall (load average 3.3 before, 4.7 after), under 45 s. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` and `make linkcheck` clean; `go generate ./...` changes nothing. No golden moved.
  - **Tier 2**: no task of this run names a tier-2 test. The read was proved live on `fylgja-test-017-read`, which is deleted (research §5.6). `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`. Nothing was written to `main`.
  - **The host**: no twin was booted. The worker (pid 2314364) and the server (pid 2314366) were not touched. A server built from this tree still refuses every read of today's fixture and `main` by conformance until T056–T060.

- [X] T044 [US1] [US2] [US3] The tier-2 tests of the read (quickstart §7; R-18), written against the re-seeded fixtures and throwaway `fylgja-test-*` branches, each deleted by the test that made it. They are run at T062; here they must compile (`go vet -tags contract ./...`).
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
  - *2026-10-26 02:40Z, Run 12 of the converge loop:* done. Every tagged file compiles (`go vet -tags contract,fixture,e2e ./...`). One test ran live and passed; the rest need the render, which is T058's, and run at T062.
    - **`read_contract_test.go`**: the read is `readUnder(branch, at, scope)`: conformance, then `Fetch` under the scope, returning the CTM, every finding of both passes and any operational failure. `read` and `tryRead` read under `tag:fylgja`, and `read` now fails on a rejection too. `seeded` makes a throwaway holding the library and the three-node seed.
      - `TestFixtureReadsToTheThreeNodeCTM` (was `TestReadReproducesTheCommittedFixture`) asserts the envelope's scope, mapping and three rows against `three-node.json`'s, then everything below the envelope byte for byte.
      - `TestCablesTheReadCannotPlace` gives a seeded branch an untagged `cs1` with `port1`, `c-out` from a new `n1:ethernet-1/3` to it, and `c-three` joining new `n1:ethernet-1/4`, `n2:ethernet-1/3` and `n3:ethernet-1/3`. It asserts the two info findings exactly, the outside end by `cs1`'s id, the two rows among five, the counts (13 interfaces, 2 cables omitted), `cs1` absent, and the new ports read and cabled to nothing.
      - `TestPlatformsTheReadRefuses` moves `n1` onto `nokia` / `SR-Linux` and takes `n2`'s platform away: `platform.unmatched n1` and `platform.missing n2`, exactly two, with no CTM.
      - `TestScopeSelectsNothing` reads the fixture, read-only, under `tag:nothing`.
      - `TestReadCountsTheFixture` counts 9 interfaces and 3 artifacts. `TestSchemaInfoReportsImplementers` checks the mapping's kinds and `used_by` in place of `ctm.RequiredGenerics` and `ContractKind`.
    - **`conformance_contract_test.go`**: `TestSchemaCheckNamesAMissingKind` loads the library, then `testdata/dcim-cable-absent.yaml`. It asserts one finding, `schema.kind.missing DcimCable`, naming the commit, and the read refusing with the same finding and no CTM. **Passed live** (258.6 s; research §5.7).
    - **`defects_contract_test.go`, rewritten rather than removed, for review**: `link.endpoints.same_device` is still reachable on a library branch and was covered live by nothing T036's and this task's cases hold. `TestSeededDefectsAreAllReportedInOnePass` now seeds the library's three validation defects on a seeded branch: a cable joining two ports of `n1` (`link.endpoints.same_device`), a cable from `n2:ethernet-1/99` (`interface.unmappable.linked`), and an uncabled `n3:console` (`interface.rule.unmatched`). It asserts exactly those three rejections, in one document. `internal/testsupport/generics.go` went with `SeedDefects`, its last caller, and so did `testsupport.ContractVersion`.
    - **`internal/cli/schema_contract_test.go`**: `TestSchemaCheckPassesOnBothFixtures` replaces `TestSchemaCheckOnTheFixtureBranch`. Through the harness's server, it checks the success line (`conformantLine`) and the `verified` block on `fylgja-fixture`, then on a `fylgja-test-mixed-*` throwaway that holds the mixed seed.
    - **`internal/stage`**:
      - `TestArtifactOnASeededBranch` lists artifacts through `DcimDevice` and expects `compiler.BundleVersion`. Its refusals add `n4` and `n5` with `AddDevice` (tagged, `Nokia` / `SR Linux`, `mgmt0`), `n5` in the group, expecting `artifact.missing` for both. The detection's comments name the description and the serial number.
      - `TestFollowingDetection` counts 9 interfaces, then 11.
      - **`TestPinnedReadReproducesItsBundle`, for review**: a pinned read filtering by tag is proved, not only asserted. `cs1` is complete but for the tag and is rendered before T, then tagged after both changes. The reads pinned to T never read it, and the unpinned one does (5 devices, 13 interfaces, 4 links, 5 artifacts). The probe saw the same with an unrendered device (research §5.7).
      - `TestMixedSeedReads`: its comment only.
    - **Test support, new**: `Device` and `AddDevice`, which writes on a test branch, refuses the fixture and a name held, and returns the id. `AddCable(label, ends...)` takes any number of `device:port` ends. `SetDevicePlatform(device, manufacturer, platform)` with an empty platform sends `platform: null`. `LoadSchemaFile(branch, path)` refuses `main` and waits until each removed kind's `Create` mutation leaves GraphQL (`waitForKindsGone`). All four were proved by the probe.
    - **For review**: tier 1's `TestCablesTheReadCannotPlace` (package `intent_test`) shares its name with tier 2's (package `intent`). Both compile, and under the contract tag `-run TestCablesTheReadCannotPlace` runs both. The spec's name is kept for tier 2 rather than renaming either.

- [X] T045 [US1] Redraw the intent component in `docs/c4/workspace.dsl`: it reads the library's DCIM by the mapping in two queries, and conformance is a table naming the commit. Then run `make diagrams`; a second run changes nothing.
  - *2026-10-26 02:40Z, Run 12 of the converge loop:* done.
    - **The component's description**: the reader of the library's DCIM at `26336e9`, by the mapping (`mapping.go`). It reads the scope's devices by their tag, then their physical ports by the devices' ids, in two queries, with each cable reached through its port's connector. Conformance is the mapping's table against the branch's schema, every finding naming the commit. Its other roles are unchanged.
    - **The relations**: the handlers check the schema "against the mapping's table", and `stage` "Reads the scope by the mapping". **One added, for review**: `intent` → `psp`, "Finds each device's package by its manufacturer and platform". The import was already there, but the model drew none, and matching by the pair is new.
    - **`make diagrams`**: it moved the server view's `.puml` and `.svg`, and the worker view's, whose one relation the exporter reordered. A second run changed nothing. The import graph and the topologies are unchanged.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`. The
MVP's reader is complete in tier 1.

---

## Phase 9: User Story 1, part 3 — the step's and the follow's reads under the record's scope (Priority: P1)

**Goal**: `twin step` and the following twin read under the scope the twin records, never
the server's default (FR-020; US1 scenario 7); the headings name the scope (R-17).

**Independent Test**: through the harness, with the server's default `tag:other` and a
record of `tag:fylgja`, `twin step`'s target read sends `tags__name__value: fylgja`.

- [X] T046 [US1] `twin step` (`internal/server/step.go`, `internal/stages/target.go`) takes the scope from the record's `provenance.scope` for the target's resolution, its staleness and its read. The following twin's reads take `ProvisionInput.Scope` through `ReconcileInput` and `ReadIntentInput` (`internal/provision/`), set at create from the request's scope. The headings of `stage plan` and `twin rehearse` end `, scope tag:fylgja` (where each is built: `internal/stages/blocks.go`, `internal/server/rehearse.go`), and the rehearsal's document carries `subject.scope`. The rehearsal's markdown report (`internal/rehearsal/markdown.go`, `parts`) names the scope in its heading after the branch (`… on branch b → main, scope tag:fylgja`), kept by `fit` as the heading is, so the comment `fylgja-twin` posts names the scope read (US5 scenario 4). Tests in `internal/rehearsal/markdown_test.go`: the heading carries it in the full and the shortened forms; `TestMarkdown`'s expected text moves. Tests:
  - the harness case above, and its follow equivalent in `internal/provision/workflow_reconcile_test.go` (the scope reaches the read activity);
  - `stage plan --scope tag:x` sends `x` on every stage's read (US5 scenario 5);
  - the nine histories replay.
  - *2026-10-26 02:40Z, Run 12 of the converge loop:* done.
    - **The step** (`internal/server/step.go`): after `stepScopeUnknown`, every read is under `rec.Provenance.Scope`, never the server's default. That covers `stages.Find`, and so the head's stamps, the target's resolution, its staleness and its read, all of which the change carries (`internal/stages/target.go` needed nothing). **One addition, for review**: the step's document carries `subject.scope`, by the contract's "whenever a read was made under one".
    - **The follow**: done at T013. `TestProvisionReadsAndFollowsUnderItsScope` and `TestReconcileReadsAndRebuildsUnderItsScope` assert the scope reaching `ReadIntentInput`, and through it the read activity. This run adds the activity's own case to `TestReadIntentActivity`, "the read is under the input's scope": a conformant schema, `Scope: "tag:edge"`, the devices asked for by `edge` alone, `scope.empty tag:edge` at step read, and nothing written.
    - **The headings**:
      - `stage plan`'s ends `, scope tag:x`. It is built by `heading` in `internal/server/stages.go`, not `internal/stages/blocks.go`. `stage list`'s is unchanged, as the contract names only the plan and the rehearsal.
      - **For review**: `twin rehearse`'s heading takes `, scope tag:fylgja` literally at its end, after the deadline (`…: 4 stages; deadline 33m0s (ceiling 1h0m0s), scope tag:fylgja`).
      - The rehearsal's document already carried `subject.scope` from T013.
    - **The markdown** (`internal/rehearsal/markdown.go`): the scope follows the branch, `## Fylgja rehearsed proposed change "x" on change-1, scope tag:fylgja`. It is taken from the document's subject and kept by `fit`, since the heading is rank 0. In the brief form it is clipped at `nameMax` as the names are. A document with no block names the scope too once it was resolved, and a refusal before it names none.
    - **Tests**:
      - `TestStepReadsUnderTheRecordsScope` (harness) has two cases. Default `tag:other` with a record of `tag:fylgja`: exit 0, every `Devices` sent `fylgja`, `subject.scope` `tag:fylgja`. Default `tag:fylgja` with a record of `tag:other`: every read sent `other`, refused `scope.empty tag:other`. Reverting the step to the default fails both cases.
      - `TestStagePlanReadsUnderTheScopeGiven`: `--scope tag:x` gives the heading, `subject.scope`, `scope.empty tag:x` on each of the four stages, and one read per stage, each sending `x`.
      - `TestRehearseMarkdown` asserts the posted heading and `subject.scope`. `TestStagePlanText`, `TestRehearseText` and `TestRehearseAnswerLost` moved.
      - In `internal/rehearsal`, the examples' subject carries `tag:fylgja` (`exampleScope`), so `TestMarkdown`'s, the fit tests' and the refusal tests' headings moved. New: a scope longer than a comment, whole in the full form and cut with an ellipsis in the brief, and the scoped heading of a document with no block.
      - The nine histories replay.

  *Run 12's checkpoint, 02:40Z*:
  - **Gates**: `make build` static. `make test` uncached took 41.0 s wall (load average 3.7 before, 6.1 after; `internal/cli` 29.9 s), under 45 s. `make lint` 0 issues. `go vet -tags contract,fixture,e2e ./...`, `make linkcheck` and `shellcheck scripts/bring-up.sh scripts/e2e.sh` are clean, and `go generate ./...` changes nothing. No golden moved.
  - **Tier 2**: of T044's tests, `TestSchemaCheckNamesAMissingKind` needs no render and passed live (258.6 s). Every other test seeds or reads the fixture, so each waits for the template's import (T058) and the re-seed (T060), and runs at T062. The new writers and the reads those tests assert were proved by an uncommitted probe (research §5.7), which also verified that a pinned read filters by the tag as it stood at T. Both branches were deleted by their tests. Afterwards `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`. Nothing was written to `main`.
  - **The host**: no twin was booted. The worker (pid 2314364) and the server (pid 2314366) were not touched; both `/proc/<pid>/exe` read `(deleted)`.

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
