# Tasks: Snapshots, the core's one input

**Input**: Design documents from `/specs/018-snapshots/`: [plan.md](plan.md),
[spec.md](spec.md), [research.md](research.md) (§1 verified at plan, §2 decisions
R-01–R-24, §3 D-061 and Constitution 2.2.0 drafted, §4 owed at implement),
[data-model.md](data-model.md), [contracts/](contracts/) (`snapshot.schema.json`,
`snapshot-commands.md`, `formats.md`), [quickstart.md](quickstart.md); the
[brief](brief.md); Constitution 2.1.0, moving to 2.2.0 at T003;
[D-011](../../docs/decisions.md#d-011), [D-014](../../docs/decisions.md#d-014),
[D-023](../../docs/decisions.md#d-023), [D-040](../../docs/decisions.md#d-040),
[D-045](../../docs/decisions.md#d-045), [D-055](../../docs/decisions.md#d-055),
[D-057](../../docs/decisions.md#d-057).

**Tests**: requested. The brief's Exit, the spec's SC-001–SC-008 and quickstart §1, §7 and
§8 name each tier's cases, and each is a task below. Every format test validates against
the contract file under `contracts/`, and every earlier format against its frozen copy.
**No golden moves**: `testdata/golden/` must be byte-identical to `main`'s after every run
(FR-026, SC-003). A run that changes it has broken the feature, and the loop will stop.

**Organization**: bottom-up, in the plan's order ("Order of the work"), because every story
stands on the same document and the same records. First the identifiers and the contract
(Phase 2). Then the snapshot, its id and its store (US2, Phase 3), the wrapped fixtures
(US4, Phase 4), and the records and the wire (US6, Phase 5). Then the create the server
takes a snapshot for (US1, Phase 6, the MVP), `--snapshot` on create (US3, Phase 7), the
hand tools (US4, Phase 8), and the stages, step and rehearsal (US5, Phase 9). Then the
tier-2 tests (US2, Phase 10), the end-to-end script and the contracts' prose (US6, Phase
11), the host, live (Phase 12), and the records at the close (Phase 13). The loop runs the
pure gates after every implement run, so every run must leave the tree green: `make
build`, static, `make test`, `make lint` (with tags `contract,fixture,e2e`, so every tagged
test must compile after every run). Story labels mark which story each task builds or
proves.

**Decisions this file takes, against or beyond the plan's text** (each for `analyze` to
settle at T004):

- **The frozen copies all go under `017-dcim-reader/`.** R-06 says to name each directory
  after the feature that last wrote the file, as `git log -1` reports it. formats.md §9
  puts all six under `017-dcim-reader/`. `git log` names 017's commits for `twin`,
  `findings`, `show` and `rehearsal`. For `stages` and `step` it names `fc709ed`, Release
  0.2's `$id` hygiene commit, which belongs to no feature. So every copy is frozen as 017
  left the tree, under `017-dcim-reader/`, as formats.md's table says. That is 16 files
  (`twin` in `internal/lab`; the other five in each of `internal/findings`,
  `internal/server` and `internal/cli`), and `frozenContractCopies` goes from 33 to 49.
  T020 confirms the count.
- **The findings subject gains `snapshot`.** `twin compile` writes `subject.ctm` today, and
  no design document says what a `--snapshot` command's subject names. This file adds
  `subject.snapshot` (optional string, the `--snapshot` argument as given: an id or a
  path) on `twin.compile` and `twin.create --snapshot`. `subject.ctm` stays in the schema
  for older documents, and no build of this tree writes it (T020, T030, T036).
- **`ObservedAtLayout` lives in `internal/snapshot`.** The plan has `internal/snapshot`
  import the CTM and nothing of the reader or the compiler. `stage.ObservedAtFormat` is in
  `internal/stage`, which imports the compiler. So the snapshot package keeps its own
  constant, and a test in an external `snapshot_test` package holds it equal to
  `stage.ObservedAtFormat` (T009).
- **The sidecar is retired before the create moves** (Phase 6, T023). Removing
  `bundle.Store.PutCTM` changes `stages.Pipeline.File`'s signature in the same compile. So
  T023 changes `File` and adds no `Take`; Phase 9 (T040) adds `Take`.

**Tags**: `[operator]` marks a task that needs the operator: a decision entry, the
constitution, a spec amendment, a commit of the operator's uncommitted edits, or the
review. `[live]` marks a task that needs the development host's server or worker restarted
from this tree, a twin, a hand check, the whole contract tier beside the server on the
bridge, or the end-to-end tier. Unattended, the loop stops at both. A single tier-2 test a
task names is not `[live]`: the loop's sessions hold Infrahub's address and token and run
it. Commits are by hand, conventional, with a body saying why, and end with the model's
`Co-Authored-By` trailer. A session never pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6, from spec.md

---

## Phase 1: Setup (the baseline and the decisions)

**Purpose**: confirm the tree's gates pass on this branch before anything changes, so any
later failure is this feature's own. Then the operator's gates: D-061, Constitution 2.2.0,
the plan's six departures with this file's four decisions, and the roadmap's edits
committed.

- [X] T001 Run the pure gates from the repository root and confirm each passes. The gates: `make build`; `file bin/fylgja` reports a statically linked executable; `make test` uncached (`GOFLAGS=-count=1`; note the wall time against the 45 s budget, and the load average); `make lint`; `go vet -tags contract,fixture,e2e ./...`; `git diff --stat main -- testdata/golden` is empty. Read, writing nothing:
  - `git status`: `docs/roadmap.md` modified and `specs/018-snapshots/` untracked, as research §1.7 found.
  - `ls local/bundles/*.ctm.json | wc -l`, the sidecars already on disk (research §1.1).
  - `ls local/snapshots 2>/dev/null` (expected: absent).
  - `pgrep -x fylgja`: the worker and the server, each `/proc/<pid>/exe`.
  - `grep -n 'D-060\|D-061' docs/decisions.md | tail -3` and the constitution's version line.

  Report the results in this task's note.
  - *2026-10-27, Run 1, the attended converge loop's session, at `176dd31`:* **done; every gate passes.** `make build` exit 0, and `file bin/fylgja` reads `statically linked`. `GOFLAGS=-count=1 make test` exit 0 in 38.9 s wall against the 45 s budget, load average 1.64 before and 3.68 after; `internal/cli` the longest at 33.9 s (`CLAUDE.md` says about 26 s), then `internal/lab` 11.2 s and `internal/provision` 8.7 s. `make lint` `0 issues`. `go vet -tags contract,fixture,e2e ./...` clean. `git diff --stat main -- testdata/golden` empty. The reads:
    - `git status`: clean on `018-snapshots`, not as research §1.7 found, because Run 2 ran first: T005 committed the roadmap's edits (`c693508`) and the design (`176dd31`).
    - `local/bundles/*.ctm.json`: **477** sidecars, beside 477 bundle directories, the newest at 00:13 today; `local/bundles/.reads/` holds the two run-named CTMs §1.1 found (10-16 and 10-21).
    - `local/snapshots`: absent.
    - `pgrep -x fylgja`: the worker (`3867740`) and the server (`3867762`), both started 14:12:58 today, each `exe` `bin/fylgja` and not deleted before this run's build. `make build` rewrote the file, so both now read `(deleted)`. `go version -m` shows that the old and new binaries differ only in their VCS stamp (`7ddd157` → `176dd31`, with only documentation commits between), so both run this tree's code. Neither was restarted: this run may not start or stop the worker, and a loop session holds no node logins to start the server with. T050 restarts both.
    - `docs/decisions.md`: D-060 at line 3679 and D-061 at line 3727. The constitution: `**Version**: 2.2.0 | **Ratified**: 2026-09-14 | **Last Amended**: 2026-10-27`.
    - For T062: Go is go1.26.8 (`golang-1.26-go 1.26.8-1~ubuntu0.26.04.2`, `/usr/bin/go`), not the go1.26.0 `CLAUDE.md` names. `go.mod`'s `go 1.26.0` is unchanged, so nothing is fetched.

- [x] T002 [operator] Put [D-061](research.md#31-d-061--the-snapshot-is-the-cores-one-input) to the operator. It says: the snapshot is the core's one input, a content-addressed wrap of an unchanged CTM `2`, stored under `snapshots/` beside the bundles; the server takes it for every create; the bundle's CTM sidecar is retired; and two limits stand, the rebase and the re-render. If accepted, append it to `docs/decisions.md` after D-060 and before "Parked", in D-060's format, with `**Status:** Accepted <date>` and its row in the index. Then grep `docs/architecture.md` for the positions it retires (`ctm.json`, `sidecar`, `.reads`, `ReadIntent`, `--ctm`, `read and compile`) and note each hit's line for T055. If declined, record the answer in `research.md` as a new §5 and build nothing past Phase 2. Blocks T009 onward.
  - *2026-10-27, the hand session at `analyze`, by the operator:* **done.** D-061 accepted as research §3.1 drafts it and appended after D-060, before Parked, in D-060's format, with its index row (area Contract). `docs/architecture.md`'s positions it retires, for T055: line 95 ("the same read and compile"), 532 and 542 (the provision and reconcile activity chains with `ReadIntent ─▶ Compile`), 570 and 573 (the worker's activities), 725 (the sequence drawing's `ReadIntent`), 1017 and 1055 (`<bundle_id>.ctm.json` in the state root tree and its paragraph), 1187–1189 (`intent read --out ctm.json` and `twin compile --ctm`).

- [x] T003 [operator] Amend the constitution to 2.2.0 as [research §3.2](research.md#32-constitution-210--220) drafts it, citing D-061, after T002. In `.specify/memory/constitution.md`: Principle VI replaced by §3.2's text (the snapshot in the provenance sentence; `observed_at` neither in the bundle nor in the bytes a snapshot's id hashes; the sentence for a source that cannot replay time; D-061 in its rationale), the Sync Impact Report, and the version line (2.2.0, Last Amended the date). In `.specify/templates/plan-template.md`: the Constitution Check's version, and row VI as §3.2's last paragraph gives it. Then in `specs/018-snapshots/plan.md`: the Constitution Check's "Constitution 2.1.0" becomes 2.2.0, and row VI's status becomes `**PASS**. Under 2.1.0 on its own: `observed_at` is in the snapshot's outer part and the twin directory, never the bundle. 2.2.0 adds the snapshot to the provenance sentence and the F-025 sentence, which binds nothing here (R-01, R-02).` Blocks T016 onward, the records' move.
  - *2026-10-27, the hand session at `analyze`, by the operator:* **done.** Constitution 2.2.0 as research §3.2 drafts it: Principle VI replaced, its rationale citing D-061, the Sync Impact Report's first entry and the version line (Last Amended 2026-10-27). The plan template's Constitution Check names 2.2.0 and its row VI reads §3.2's last paragraph. `plan.md`'s Constitution Check names 2.2.0 and its row VI the status this task gives; its Input line records the amendment. `CLAUDE.md`'s mention of 2.1.0 is T062's.

- [x] T004 [operator] Settle at `analyze` the plan's six departures from the spec (plan, Summary) and this file's four decisions (the header above). Amend `spec.md` where an answer changes its text. The plan's six:
  - (a) tier 3's sidecar assertion is moved, not dropped, and reads "no sidecar newer than the case's start" (R-17);
  - (b) a compile refused after a clean read leaves the snapshot filed (R-05; FR-010 names a refused read alone);
  - (c) `--scope` beside `--snapshot` is refused too (R-07; FR-018 names three flags);
  - (d) `twin verify`'s block keeps naming the bundle alone (R-21);
  - (e) a record of `8` can still step, with a from side naming no snapshot (R-06);
  - (f) the provision workflow keeps its read-and-compile branch for the recorded histories (R-10).
  - *2026-10-27, the hand session at `analyze`, by the operator:* **done.** The operator accepts the plan's reading of (a)–(f) and this file's four decisions. (b), (c) and (d) are now in the spec's text, amended by `analyze`: FR-010 (a refused compile leaves the snapshot filed and named), FR-018 and its edge case (`--scope`, the first flag found in order), SC-005 (FR-022's five records) with a new Assumption for `twin verify`'s block. `analyze` also amended FR-014 (the dry run prints paths, the plan prints ids, as `printPlanned` prints the bundle id alone today), and this file: T003 re-cites `plan.md`; T011 carries the C4 redraw of the package and the store, leaving T029 the handler and stages relations; T017's workflow test covers the create's `Source: intent` input beside `Source: snapshot`; Phase 2 depends on T002; T021 is `[US6]`; T036 names no `required` list. Open at `analyze` and left as the plan reads them: the kind line's `built from snapshot <id8>…` suffix beside the note (R-08), and the inner CTM's faults keeping the CTM's own rules (R-03).

  This file builds the plan's reading of (a)–(f), plus `subject.snapshot`, the frozen copies under `017-dcim-reader/`, `snapshot.ObservedAtLayout`, and the sidecar retired before `Take`. A different answer changes T020 (frozen copies, subject), T030 (c), T047 (a) or T026 (b). Record the operator's answers in this task's note.

- [x] T005 [operator] Commit the roadmap's uncommitted F-024 and F-026 edits (`docs/roadmap.md`, research §1.7) and the feature's design directory (`specs/018-snapshots/`: brief, spec, plan, research, data-model, quickstart, contracts, checklists, this file). Use conventional commits whose bodies say why (`docs(roadmap): …`, `docs(018): …`). The operator's: the edits are theirs.
  - *2026-10-27, the hand session at `analyze`, by the operator:* **done in this commit** for the design directory (`docs(018): …`), after three commits by hand: the roadmap's F-024 and F-026 edits at `c693508`, D-061 at `9378915`, Constitution 2.2.0 with the plan template at `4fc1635`. `make linkcheck` was clean but for the roadmap's two links to the then-untracked brief, which this commit resolves. Nothing pushed.

**Checkpoint**: baseline green; D-061 and 2.2.0 accepted; the departures settled; the
design committed.

---

## Phase 2: Foundational — the identifiers, the contract and the path

**Purpose**: the five identifiers, the snapshot's contract and the store's directory, so
every later task files by constant, validates against the contract, and names the path
one way.

- [X] T006 [P] In `internal/findings/finding.go`, add the five rule constants of [contracts/snapshot-commands.md](contracts/snapshot-commands.md) "Identifiers" as one block, "018, snapshots": `RuleSnapshotInvalid` (`snapshot.invalid`), `RuleSnapshotVersionUnsupported` (`snapshot.version.unsupported`), `RuleSnapshotIDMismatch` (`snapshot.id.mismatch`), `RuleSnapshotUnknown` (`snapshot.unknown`), `RuleSnapshotFlagsConflict` (`snapshot.flags.conflict`). Each gets the house comment with the table's severity, exit, step and object exactly. For example: `// rejection, exit 2, start: the flag; --snapshot beside --branch, --stage, --at or --scope, the first found in that order`. Add `FollowReasonSnapshot = "snapshot" // --snapshot given: a twin built from a snapshot never follows (018)` beside `FollowReasonStage` in `internal/findings/render.go`. Register the five rules in `internal/findings/finding_test.go`'s `dataModelRules` as an appended 018 block. Extend `RuleFollowFlagsConflict`'s comment with the `--snapshot` case. Nothing files them yet.
  - *2026-10-27, Run 3, the converge loop's session, at `f40021b`:* **done.** The five constants are one block after 017's in `internal/findings/finding.go`, headed "018, snapshots", in the table's order. Each comment gives the table's severity, exit, step, object and when; the table's `none` is written `no step`, as `ctm.version.unsupported`'s comment writes it. `RuleFollowFlagsConflict`'s comment names `--snapshot`. `FollowReasonSnapshot` sits beside `FollowReasonStage` in `render.go`. `dataModelRules` gains the five as an appended 018 block, so `TestEveryDataModelRuleHasAConstant` and its converse hold. Nothing files them. `contracts/findings.schema.json`'s `dry_run.follow.reason` enum does not name `snapshot` yet: T020 adds it, and nothing emits the reason before T030.

- [X] T007 [P] Land the contract. Copy [contracts/snapshot.schema.json](contracts/snapshot.schema.json) byte for byte to `contracts/snapshot.schema.json`. Its `$id` is `https://github.com/happypathnetworking/fylgja/contracts/snapshot/v1`, its `ctm` a `$ref` to CTM 2's `$id`, and its description holds the hashed-bytes sentence and the hand recipe (FR-004). Check that every test that loads `contracts/*.schema.json` by glob, or holds the `$id` namespace ([D-055](../../docs/decisions.md#d-055)), finds and accepts it. Grep `internal/` for `contracts/\*.schema.json` and for `fylgja/contracts/`, and add the file to any explicit list such a test keeps.
  - *2026-10-27, Run 3, the converge loop's session, at `f40021b`:* **done.** `contracts/snapshot.schema.json` is the design's file byte for byte (`cmp`). No test loads `contracts/*.schema.json` by glob or holds the `$id` namespace: the one glob is `TestFrozenContractCopiesAgree`'s, over `../*/testdata/contracts/`, and no Go file names `happypathnetworking/fylgja/contracts/`. So no list gained the file, and nothing embeds `contracts/`. A throwaway test, removed before the commit, compiled the schema with `ctm.schema.json` registered under its `$id`. It accepted `testdata/ctm/three-node.json` wrapped as `{"snapshot_version": "1", "ctm": …, "probes": []}`, and refused `probes: [{}]` and `snapshot_version: "2"`. T013's `TestSnapshotSatisfiesTheContract` makes that check permanent.

- [X] T008 [P] Add `Snapshots string` to `lab.Paths` in `internal/lab/env.go`: `<state root>/snapshots`, beside `Bundles` and `Twin`, made by the same constructor. Name it in the state root lines. `cmd/fylgja/serve.go` line 279 becomes `state root %s (bundles: %s, snapshots: %s, twin: %s)`, and the worker's line in `cmd/fylgja/worker.go` changes the same way. Update `cmd/fylgja/serve_test.go`'s and `worker_test.go`'s pinned lines, and `CLAUDE.md`'s description of the server's report is left for T062. The directory is created by the store's first `Put`, never at start.
  - *2026-10-27, Run 3, the converge loop's session, at `f40021b`:* **done.** `lab.Paths.Snapshots` is `<root>/snapshots`, after `Bundles`, set by `PathsAt`. Nothing creates it at start: the store's first `Put` (T011) will. The serve report's line in `cmd/fylgja/serve.go` and the worker's now read `state root %s (bundles: %s, snapshots: %s, twin: %s)`. The worker's line is in `internal/provision/worker.go` (`StartupReport`), not `cmd/fylgja/worker.go`, so its pinned line is in `internal/provision/worker_test.go` (`TestStartupReportClearHost`). The pinned lines in `cmd/fylgja/serve_test.go` (two) and `internal/lab/env_test.go`'s `want` are updated too. `lab.Paths` crosses no workflow payload, only the activities' struct, so no recorded history moves. `contracts/cli.md`'s M13 report example (line 45) still shows 017's line without the default scope, so it is left for T048 to decide. `CLAUDE.md`'s description of the report is T062's. The running server and worker still print the old line until T050 restarts them. The run's checkpoint: `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` passed twice. The first run took 47.6 s wall at load 3.20 → 5.20, because it rebuilt every test binary that depends on `internal/findings`; `internal/cli` took 34.1 s, as at T001. The second took 37.9 s at load 5.46 → 5.32, under the 45 s budget. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `git diff --stat main -- testdata/golden` empty. No task in this run names a tier-2 test, so none ran, and Infrahub was not touched.

**Checkpoint**: `make test`, `make lint`; nothing files a snapshot yet.

---

## Phase 3: User Story 2, part 1 — the snapshot, its id and its store (Priority: P1)

**Goal**: `internal/snapshot`, the document of version `1`, the id R-01 defines, the
refusals in R-03's order and the store R-04 defines, proved in tier 1 (FR-001–FR-007).

**Independent Test**: `go test ./internal/snapshot` proves, over `testdata/ctm/`, that:
`three-node.json`, `observed-later.json` and `three-node.shuffled.json` wrap to one id
(`6a8a77fc…` by research §1.3, a candidate); a changed artifact byte or fidelity row moves
it; a test-local recomputation equals the stored id; each refusal fires under its rule;
`Put` twice writes nothing the second time.

- [X] T009 [US2] Create `internal/snapshot/snapshot.go`, a package that imports `internal/ctm` and the standard library alone (data-model §1, §2; R-01, R-02).
  - `const Version = "1"`, and `const ObservedAtLayout = "2006-01-02T15:04:05.000000Z"`.
  - `type Snapshot struct { Version string \`json:"snapshot_version"\`; ID string \`json:"snapshot_id"\`; ObservedAt string \`json:"observed_at"\`; CTM *ctm.CTM \`json:"ctm"\`; Probes []json.RawMessage \`json:"probes"\` }`, in that field order. That order is the stored order: the outer part first.
  - `Take(c *ctm.CTM) *Snapshot`, pure. It deep-copies `c` through `ctm.Marshal`/`ctm.Unmarshal` so the caller's CTM is untouched, sets `Version`, copies `c.Envelope.ObservedAt` to `ObservedAt`, sets `Probes` to an empty non-nil slice, and computes `ID`.
  - `Hashed(s *Snapshot) ([]byte, error)`: the hashed bytes, `{"ctm": …, "probes": []}`. The CTM is normalised and its envelope written through an unexported `hashedEnvelope` type that lists `ctm.Envelope`'s fields but `ObservedAt`, in its order and with its tags. Encoding as `ctm.Marshal`: `json.MarshalIndent` with two spaces, a trailing LF, Go's default escaping.
  - `ID(s *Snapshot) (string, error)`: the lowercase-hex SHA-256 of `Hashed`. `IsID(s string) bool`: 64 lowercase hex characters, `bundle.IsID`'s rule. Copy the rule; do not import `internal/bundle`.
  - `Marshal(s *Snapshot) ([]byte, error)`: the stored form. Two-space indent, LF, a trailing newline, the CTM normalised.

  Tests in `internal/snapshot/id_test.go`:
  - `TestHashedEnvelopeMirrorsTheCTMEnvelope`, by reflection: every `ctm.Envelope` field but `ObservedAt`, same names, types, tags and order. A field added to the envelope fails tier 1.
  - In an external `snapshot_test` file, `TestObservedAtLayoutIsTheStages`: `snapshot.ObservedAtLayout == stage.ObservedAtFormat`.
  - `TestTakeLeavesItsInputAlone`.

  - *2026-10-27, Run 4, the converge loop's session, at `4b2ac88`:* **done.** `internal/snapshot/snapshot.go` imports `internal/ctm` and the standard library alone, and `TestSnapshotImportsTheCTMAlone` holds it so, as `internal/stage` holds its own imports. `Take` copies through a plain `encoding/json` round trip, then normalises the copy. It does not use `ctm.Marshal`/`ctm.Unmarshal` for the copy: `ctm.Marshal` normalises its argument in place, and `TestTakeLeavesItsInputAlone` caught that with the shuffled fixture; `ctm.Unmarshal` also refuses an in-memory CTM whose lists are still nil. `Take` has no error in its signature, so it panics on an encoding failure, which a CTM cannot have. `hashedCTM` sits beside `hashedEnvelope`, and a second reflection test, `TestHashedCTMMirrorsTheCTM`, holds it to `ctm.CTM`, so a field added to the CTM's top level fails tier 1 as an envelope field does. `Hashed` normalises in place, as `ctm.Marshal` does. `Marshal` refuses a snapshot that breaks version 1's invariants: an id that is not the body's hash, another version, an `observed_at` that is not the CTM's, a probe, or no CTM. So nothing writes a document `Unmarshal` would refuse.

- [X] T010 [US2] `Unmarshal(data []byte) (*Snapshot, error)` in `internal/snapshot/json.go`, strict, in R-03's order (data-model §1).
  1. `snapshot_version` decoded on its own: not `"1"`, or absent, is `*VersionError{Got}`. Its message names the version read, or that none was, and `"1"`, worded as [snapshot-commands.md](contracts/snapshot-commands.md) "The text" gives it. A bare CTM is refused here.
  2. The outer shape, decoded with `DisallowUnknownFields` into a raw struct, each fault an `*InvalidError{Field, Message}`. The faults, by field:
     - an unknown key, named;
     - `ctm` absent, null or not an object;
     - `probes` absent, null, not a list, or not empty: `probes holds 1 entry; in snapshot 1 the list is required and empty, since 016 defines its element`;
     - `snapshot_id` present and not `IsID`;
     - `observed_at` present and not parsable by `ObservedAtLayout`, or not equal to the inner CTM's.
  3. The inner CTM under `ctm.Unmarshal`. `*ctm.VersionError` is returned as is. `*ctm.MissingError` has its `Field` prefixed `ctm.` (`ctm.envelope.fidelity`, `ctm.links`, `ctm.devices[<i>].interfaces`); its message keeps the field name and is prefixed the same way.
  4. `observed_at` filled from the inner CTM when absent.
  5. The id computed. When declared and different, `*IDMismatchError{Declared, Computed}`, whose message reads `declares snapshot_id <declared>, but its body hashes to <computed>; leave snapshot_id out to have it computed`. When absent, it is set.

  `Load(path)` and `Save(s, path)` (atomic: a temporary sibling, then a rename) for tests and the client. Tests in `internal/snapshot/snapshot_test.go`: one case per refusal, with its error type, its field and its message's key words. The cases: `snapshot_version` `"2"` and absent; a bare CTM file; an unknown outer key; `probes` absent, null and `[{}]`; `snapshot_id` `"ABC"` and a wrong 64-hex id; `observed_at` malformed and unequal; a wrapped CTM `1` (`ctm.VersionError`); a wrapped CTM missing its fidelity list (`ctm.envelope.fidelity`). A file with neither `snapshot_id` nor `observed_at` is accepted with both filled.

  - *2026-10-27, Run 4, the converge loop's session, at `4b2ac88`:* **done.** `Unmarshal` reads the outer object as a map, not as a struct with `DisallowUnknownFields`. Keys then match exactly, where a struct decode folds case. The unknown key is named from the map, the first in byte order, where the decoder's error names it only in its text. A document that is not an object, or is `null`, is an `*InvalidError` with no `Field`, and the server names the file. A `snapshot_version` that is not a string is a `*VersionError` naming its JSON text (`declares snapshot_version 1`). Step 2 checks `observed_at`'s equality against the inner envelope, read leniently before the CTM is decoded. An inner decode failure other than the two typed ones, such as an unknown key inside the CTM, stays a plain error, as `twin compile`'s CTM decode failure is the operation's today. For T031: a wrapped CTM recording no `observed_at`, with none outside, passes `Unmarshal` with `observed_at` `""`. Validation then refuses it at compile (`data.required.missing`, `observed_at`), and T031's order files it before the compile. The tests: `TestUnmarshalRefusals` (24 cases, the task's and `ctm` absent, null and not an object, `probes` not a list, an uppercase id, a key spelled another way, links and a device's ports missing, a non-object document), `TestUnmarshalRefusesInOrder`, `TestUnmarshalFillsTheOuterPart`, `TestStoredFormRoundTrips`, `TestStoredFormOrder`, `TestMarshalRefusesABrokenSnapshot` and `TestSaveAndLoad`.

- [X] T011 [US2] Write the store in `internal/snapshot/store.go` (R-04; data-model §3).
  - The interface: `type Store interface { Put(ctx, *Snapshot) (string, error); Has(ctx, id string) (bool, error); Path(id string) string; Fetch(ctx, id string) (*Snapshot, error) }`.
  - `NewDirStore(root string) *DirStore` on `<state root>/snapshots/`, created on the first `Put` with mode `0755`.
  - An entry is `<root>/<id>.json`, mode `0644`, written as `Marshal` writes it, to a temporary sibling and then renamed.
  - `Put` of an id already held reads the entry back, re-hashes its body, and keeps it, writing nothing; it returns the id. An entry that hashes to another id is `*ErrIDMismatch{Path, Want, Got}`, worded as `bundle.ErrIDMismatch` is.
  - `Has` is false for an absent entry and for a corrupt one.
  - `Fetch` reads through `Unmarshal` and verifies the id. An absent entry is an error matching `errors.Is(err, fs.ErrNotExist)`.

  Mirror `internal/bundle/store.go`'s shape and comments: two interfaces of one shape, not one generic.

  Redraw in the same change (`CLAUDE.md`, "A changed package … is redrawn"): in `docs/c4/workspace.dsl`, the server's `snapshot` component ("The snapshot: the document, its id, its validation, the store.", `internal/snapshot`), the container `Snapshot store` (`<state root>/snapshots/<snapshot_id>.json`), the relation `server -> snapshot store "Files and reads snapshots"`, and the deployment's state root naming `snapshots/`. Then `make diagrams`, and commit the views with the model.

  - *2026-10-27, Run 4, the converge loop's session, at `4b2ac88`:* **done.** `Put` links its temporary file into place instead of renaming it. A rename replaces a file already there, so two racing `Put`s could replace the first take's `observed_at`. A link fails on an existing entry, which `Put` then verifies and keeps. `Has` is false for an entry that hashes to another id and for one that is no snapshot at all (an unexported `entryError`). `Fetch` of an absent entry wraps `os.ErrNotExist`. `Has` and `Fetch` refuse anything but an id before joining it to the root. The C4 model has the component, the container (`<state root>/snapshots/<snapshot_id>.json: every snapshot taken, each kept as first filed.`), the relation and the state root's `snapshots/`. `make diagrams` ran twice with the same output. The worker's view moved only by the exporter's order of three relations. The import graph in `docs/development.md` gained `internal/snapshot → internal/ctm`, and also `internal/lab → internal/ctm`, an import `3565e49` added in 017's convergence without regenerating the graph.

- [X] T012 [P] [US2] The id's rules over the fixtures, in `internal/snapshot/id_test.go`. These are US2's acceptance scenarios 1–4 and the brief's tier-1 exit.
  - `TestObservedAtIsNotHashed`: `three-node.json` and `observed-later.json` wrap to one id, and their stored bytes differ.
  - `TestOrderIsNotHashed`: each of `three-node`, `lossy` and `mixed` has the same id as its `.shuffled.json`.
  - `TestAnArtifactByteMovesTheID`: one byte of one device's artifact `content` changed (with its checksum recomputed by `ctm.ChecksumOf`, so the CTM stays valid).
  - `TestAFidelityRowMovesTheID`: one row added, and one row's `reason` altered.
  - `TestEnvelopeFieldsMoveTheID`: branch, `at`, schema hash, scope and mapping version, each changed alone.
  - `TestStoredIDIsTheBodysHash`: an independent computation by a test-local struct that does not use `Hashed`. It marshals the stored document's body, deletes the inner `observed_at` through a `map[string]any` round-trip with the CTM's field order kept by a test-local struct, and SHA-256s it. It must equal `ID`.

  Log the three fixtures' ids with `t.Logf` (R-15: the implementation's values stand, research §1.3's are candidates).

  - *2026-10-27, Run 4, the converge loop's session, at `4b2ac88`:* **done.** The shipped code's ids equal research §1.3's candidates: `three-node` (and `observed-later`, and the shuffled copy) `6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6`, `lossy` `91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c`, `mixed` `37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf`. `TestOrderIsNotHashed` decodes each `.shuffled.json` with `encoding/json` alone, because `ctm.Load` would normalise it first and prove nothing. `TestStoredIDIsTheBodysHash` recomputes the id with a test-local reader that keeps each object's keys in order. It deletes the recipe's four keys and writes the rest back with a two-space indent and a trailing newline: the `jq` recipe, in Go. So it shares no type with `Hashed`, where a struct mirroring the CTM would. `TestEnvelopeFieldsMoveTheID` also covers `at` left out. A hand check ran the `jq` recipe of `snapshot.schema.json` over the three stored takes (scratch files, since removed) and got the same three ids.

- [X] T013 [P] [US2] The store and the contract, in `internal/snapshot/store_test.go` and `contract_test.go`.
  - `TestPutKeepsTheFirstTake`: `Put` of two takes differing only in `observed_at` returns one id, and the entry's bytes and modification time are unchanged by the second `Put`. This is FR-007 and the brief's "the first take's".
  - `TestPutRefusesACorruptEntry`: an entry overwritten by hand with another body is `ErrIDMismatch` naming the path.
  - `TestFetchUnknownIsNotExist`.
  - `TestHasIsFalseForACorruptEntry`.
  - `TestSnapshotSatisfiesTheContract`: `Marshal` of each fixture's take validates against `contracts/snapshot.schema.json`, with `contracts/ctm.schema.json` registered for the `$ref`, through the `jsonschema` library the other contract tests use. Two documents are refused by the schema: one with `probes: [{}]`, and one with `snapshot_version: "2"`.

  - *2026-10-27, Run 4, the converge loop's session, at `4b2ac88`:* **done.** The task's five tests, plus `TestPutFilesUnderTheID` (the store made on the first `Put` with mode `0755`, the entry `0644` as `Marshal` writes it, nothing left beside it) and `TestStoreRefusesWhatIsNotAnID`. `TestPutKeepsTheFirstTake` back-dates the entry by an hour, so a rewrite within the clock's resolution cannot hide. `TestPutRefusesACorruptEntry` covers another snapshot's document under the id and an edited body. In both, `Put` leaves the corrupt entry as it was, and the message is `bundle.ErrIDMismatch`'s. The contract test registers `ctm.schema.json` under its `$id`. The run's checkpoint: `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` exit 0 in 38.3 s wall at load 2.40 → 3.47, with `internal/cli` 34.0 s and `internal/snapshot` 0.2 s. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `git diff --stat main -- testdata/golden` empty. No task in this run names a tier-2 test, so none ran, and Infrahub was not touched. `make build` rewrote `bin/fylgja`, so the running worker and server read `(deleted)`. Neither was restarted: the worker is not this run's to stop, and the server waits for T050. `internal/snapshot` is used by nothing yet.

**Checkpoint**: `make test`, `make lint`; `internal/snapshot` complete and used by nothing.

---

## Phase 4: User Story 4, part 1 — the wrapped fixtures compile to the goldens (Priority: P2)

**Goal**: `testdata/snapshot/` holds the three fixture CTMs wrapped, each compiling to its
golden byte for byte (FR-021, SC-003; R-15).

**Independent Test**: `go test ./internal/stage -run TestWrappedFixturesCompileToTheGoldens`
passes, and `git diff --stat main -- testdata/golden` is empty.

- [X] T014 [US4] Write `testdata/snapshot/three-node.json`, `lossy.json` and `mixed.json`: each `testdata/ctm/<name>.json` loaded, wrapped by `snapshot.Take` and written by `snapshot.Marshal`. Generate them with a test in `internal/snapshot/fixtures_test.go`, `TestWrappedFixtures`, behind an `-update` flag, as `internal/compiler`'s goldens are generated. Without the flag, it holds each file equal to a fresh take of its CTM, its inner CTM equal to the `testdata/ctm/` file after `ctm.Marshal`, and its `snapshot_id` equal to `snapshot.ID`. Commit the three files; record their ids in this task's note.

  - *2026-10-27, Run 5, the converge loop's session, at `64b1dff`:* **done.** `go test ./internal/snapshot -run TestWrappedFixtures -update` wrote the three files (6,780, 6,346 and 5,973 bytes), and without the flag the test holds the three properties the task names. It also loads each file through `snapshot.Load`, the strict reader, and pins each id, as the compiler's tests pin the goldens' bundle ids: a moved id means the CTM fixture or the hashed bytes' encoding moved, and the encoding moving moves every stored snapshot's id. The ids equal research §1.3's and T012's: `three-node` `6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6`, `lossy` `91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c`, `mixed` `37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf`. By hand, `snapshot.schema.json`'s `jq` recipe over each committed file gives the same three ids, and each file's `ctm` equals its `testdata/ctm/` file under `jq .`. No test or script walks the whole of `testdata/`, so the new directory is read by these two tests alone.

- [X] T015 [US4] Add `TestWrappedFixturesCompileToTheGoldens` in `internal/stage` (a tier-1 test file, no build tag). For each wrapped fixture: `snapshot.Load`, then `stage.Compile` of its CTM with the shipped registry. The bundle's files must equal `testdata/golden/<name>/` byte for byte, and its id must be `43d91715…`, `4213b3cf…` and `ecb665f5…` in turn. It must also equal the compile of the bare `testdata/ctm/<name>.json`. `TestCompilerIsPure` and the golden tests stay untouched. Confirm `git diff --stat main -- testdata/golden` is empty.

  - *2026-10-27, Run 5, the converge loop's session, at `64b1dff`:* **done**, in `internal/stage/wrapped_test.go`. One departure from the task's text: the lossy fixture compiles through the design-case package beside the shipped ones (`testdata/psp/lossy`, as `--psp-dir` gives it), because its golden was compiled that way (`internal/compiler`'s `TestGoldenLossy`) and the shipped packages alone have no package for its chassis platform. FR-021 asks that each wrapped fixture compile to its golden, so the golden's registry is the one used. `three-node` and `mixed` compile with the shipped registry. Each bundle is compared with `bundle.LoadFiles` of its golden in both directions, so a file gained or lost fails as a changed byte does. The ids are the goldens' full ids, and each wrapped compile equals its bare CTM's in files and id. The test is in package `stage` and imports `internal/snapshot` as a test import only, which the import graph does not draw (`go list`'s `.Imports`). The goldens' and the purity tests are untouched, and `git diff --stat main -- testdata/golden` is empty. The run's checkpoint: `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` exit 0 in 38.6 s wall at load 2.16 → 3.81, with `internal/cli` 33.9 s, `internal/snapshot` 0.2 s and `internal/stage` 0.1 s. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean. No task in this run names a tier-2 test, so none ran, and Infrahub was not touched. `make build` rewrote `bin/fylgja`, so the running worker and server still read `(deleted)`, as after Run 4. Neither was restarted: the worker is not this run's to stop, and the server waits for T050.

**Checkpoint**: `make test`, `make lint`; no golden moved.

---

## Phase 5: User Story 6, part 1 — the records and the wire (Priority: P3)

**Goal**: `twin.json` `9`, the workflow inputs carrying the id, the findings blocks and the
five moved contracts with their frozen copies, and the rehearsal's column. Records only:
nothing yet sets a snapshot id but the tests (FR-022–FR-025, SC-005, SC-007; R-06, R-10,
R-14, R-20).

**Independent Test**: `go test ./internal/lab ./internal/findings ./internal/provision
./internal/rehearsal ./internal/server ./internal/cli` shows: a `9` validates against the
contract; an `8` validates against the frozen copy and reads with no snapshot; the nine
histories replay; `TestFrozenContractCopiesAgree` counts 49.

- [X] T016 [US6] `twin.json` `9`. First freeze: copy `contracts/twin.schema.json` byte for byte to `internal/lab/testdata/contracts/017-dcim-reader/twin.schema.json`. Then edit the contract and the code as follows.
  - `contracts/twin.schema.json`: per [formats.md](contracts/formats.md) §2. `$id …/contracts/twin/v9`; `twin_version` `const "9"`; top-level `snapshot_id` required, `{"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}`; `source` enum `["intent", "bundle", "snapshot"]` with R-20's descriptions; `step.properties.from` and `.to` gain an optional `snapshot_id`; `observed_at`'s description is reworded; and the description gains formats.md §2's 018 sentence quoted.
  - `internal/lab/twin.go`: `TwinVersion = "9"`, with the version comment's 9 line.
  - `internal/lab/wire/types.go`: `SourceSnapshot = "snapshot"` with R-20's comment, and `SourceIntent`'s comment reworded as R-20 gives it. `TwinRecord.SnapshotID *string` (`json:"snapshot_id"`, written as an explicit `null` when nil). `StepSide.SnapshotID string` (`json:"snapshot_id,omitempty"`).
  - `RecordFields.SnapshotID string`. `NewRecord`'s rules by `Source` (data-model §5.1):
    - `intent`: `ObservedAt` required, `SnapshotID` as given, `""` for a rebuild's provision.
    - `snapshot`: `ObservedAt` and `SnapshotID` required, `Stage` refused, `At` as the envelope has it.
    - `bundle`: `ObservedAt`, `SnapshotID` and `Stage` refused.
    - A given `SnapshotID` must satisfy `snapshot.IsID`.
  - `NewStepRecord`: a stepped or unchanged step moves the top level's `SnapshotID` to `To.SnapshotID`, or nil when empty; a diverged step keeps the previous record's. `ReadRecord` reads an `8` with `SnapshotID` nil and no side ids.

  Tests in `internal/lab/twin_test.go`:
  - every `9` `NewRecord` and `NewStepRecord` writes validates against `contracts/twin.schema.json`;
  - the existing `8` fixtures validate against `twinSchemaOf(t, "017-dcim-reader")`;
  - `NewRecord` refuses `snapshot` without an id and `bundle` with one, and accepts `intent` without one;
  - a step from an `8` record writes a from side with no `snapshot_id` and a to side with one.

  - *2026-10-27, Run 6, the converge loop's session, at `93a6052`:* **done.** `git log -1 -- contracts/twin.schema.json` names `4a62675`, 017's, so the `8` is frozen under `internal/lab/testdata/contracts/017-dcim-reader/` (`cmp` equal), and `frozenContractCopies` moves from 33 to 34; T020's fifteen bring it to 49. The contract is formats.md §2's, its description quoting the 018 sentence verbatim, plus three conditionals the table does not name. The `allOf` rule that held `observed_at` to a string on `intent` and to null otherwise now names `intent` and `snapshot`, since a snapshot record's `observed_at` is the stored take's. Two new rules mirror `NewRecord`: `source` `snapshot` holds `snapshot_id` to a string, and `bundle` holds it to null. They hold after a step too: only a stage twin steps, and a stage twin is always `intent`. `snapshot_id` sits before `bundle_id` in `TwinRecord` and `StepSide`, as the text prints the snapshot above the bundle. `wire.RecordInput.SnapshotID`, which T017 names, is added here, because `RecordTwin` copies it into `RecordFields`. `internal/lab` now imports `internal/snapshot` for `snapshot.IsID`. `scripts/diagrams.sh` regenerated the import graph, and only that edge moved. The C4 model draws no relation for it, as it draws none for `lab → ctm`. The tests are `TestRecord9` (each source's rule, the contract refusing what `NewRecord` refuses, a step's top level and sides, a step from an `8` record, a side's bad id) and `TestRecord8ReadsWithNoSnapshot` (against the frozen copy). `TestRecordTwin` gains "names the snapshot it was given" for `intent` and `snapshot`. Renames follow 017's pattern: `TestRecord8` becomes `TestRecordNamesItsProvenance`, and `TestCreateWritesVersion8`, `TestVersion8RecordCarriesEachWait` and `TestVersion8RecordRoundTrips` become `9`. An `unsnapshotted` helper, beside `contractProvenance` in `internal/lab`'s and `internal/cli`'s tests, drops the key wherever a test writes a record of `8` or earlier. Beyond the task's files: `scripts/e2e.sh`'s four `.twin_version=="8"` checks and three comments move to `9`, because `TestE2EScriptExpectsTheRecordsVersion` holds them to `TwinVersion` (shellcheck clean). `internal/cli`'s pinned versions in `show_test.go` and `stage_create_test.go` move to `9` (`TestShowCreatedVersion8RecordAsM11` is renamed with `9`). `TestShowTreatsAnUnreadableScopeAsUnknown` now reads `(record 9 names …)`, since its record is the `9` this build writes. `show.schema.json`'s `record.source` enum gains `snapshot` at T020, and no record names that source before T031.

- [X] T017 [US6] The workflow inputs (R-10; data-model §5.2). `ProvisionInput.SnapshotID string` (`json:"snapshot_id,omitempty"`) in `internal/provision/types.go`, with a comment in the house style ("The run branches on nothing of it. Empty in every recorded history before 018, and omitted when empty, so they replay."). Also widen `Source`'s comment to name `wire.SourceSnapshot`. Add `wire.RecordInput.SnapshotID string` (`omitempty`) and `RehearseStage.SnapshotID string` (`omitempty`). `StepSide.SnapshotID` is T016's. Pass `in.SnapshotID` into the record input in `internal/provision/workflow_provision.go`'s record step, and the record activity into `RecordFields.SnapshotID`. A `Source: snapshot` input with `BundleID` set takes the existing already-compiled branch (`case in.BundleID != ""`): confirm by reading `Provision` that no branch tests `Source == SourceIntent` before it, and change nothing else in the workflow. Leave `readAndCompile`, `ReadIntent`, `ReadOptions` and the reconcile untouched (FR-013). Run `go test ./internal/provision -run Replay`: the nine histories replay. Add one tier-1 workflow test (the test environment the package's workflow tests use). In it, two inputs each schedule no `ReadIntent` and no `Compile` activity, and each `RecordTwin` input carries the id: `ProvisionInput{Source: intent, Branch, BundleID, BundlePath, ObservedAt, SnapshotID, StopFollowing: true}`, the shape T025's create sends, and `ProvisionInput{Source: snapshot, BundleID, BundlePath, ObservedAt, SnapshotID}`, T031's. That is SC-001's tier-1 half for both creates.

  - *2026-10-27, Run 6, the converge loop's session, at `93a6052`:* **done.** `ProvisionInput.SnapshotID` and `RehearseStage.SnapshotID` are added, each `omitempty` with the house comment, and `Source`'s comment names `wire.SourceSnapshot`. `RecordInput.SnapshotID` came with T016. `Provision`'s switch tests `in.Source == wire.SourceBundle`, then `in.BundleID != ""`, then falls to `readAndCompile`. No branch tests `SourceIntent`, so a `snapshot` input with `BundleID` set takes the already-compiled branch. The workflow's one change is `SnapshotID: in.SnapshotID` in the record input; its doc comment also names the two compiled creates. `readAndCompile`, `ReadIntent`, `ReadOptions` and the reconcile are untouched. `go test ./internal/provision -run Replay`: the nine histories replay. `TestProvisionCreatesCarryTheirSnapshot` runs both inputs. Neither schedules `ReadIntent` or `Compile`, the host check comes first with the given bundle, and each `RecordTwin` input carries the id, the source and the `observed_at`. The intent input also stops following. `TestAnInputWithNoStageSerialisesAsBefore` now also holds `snapshot_id` absent when empty on `ProvisionInput`, `RecordInput`, `StepInput`'s sides and `RehearseStage`.

- [X] T018 [US6] The step and rehearsal workflows carry the sides' ids as data. `internal/provision/workflow_step.go` and `workflow_rehearse.go` copy `StepSide` and `RehearseStage` as they are, so read both and confirm that no field is rebuilt by hand in a way that would drop `SnapshotID`. Fix any copy that would drop it. Extend a step workflow test and a rehearse workflow test so that a side's `SnapshotID` reaches the record step's input. The replay test still passes.

  - *2026-10-27, Run 6, the converge loop's session, at `93a6052`:* **done; nothing needed fixing.** The step workflow gives the record step `From: in.From, To: in.To`. `RecordStep` passes them to `StepFields` whole, and `NewStepRecord`'s `stepBlock` clears `Branch` alone. The rehearsal copies `*s.Provision` and adds only its reference and `StopFollowing`, and it starts the step child with `*s.Step` whole. `RehearseStage.SnapshotID` is data the run never reads, for the server's report (T043). The only sides built by hand are the server's: `internal/server/step.go:366–367`, and `rehearse.go:293` and `356–357`. T042 and T043 fill them. `TestStepStepped` gives both sides an id, and the record step's input names both. `TestRecordStep` gains "names each side's snapshot": the written record names the target's at the top level and each side's in `step`, against the 9 contract. The rehearse fixture now carries `snapshotOf(label)` (beside `bundleOf`, through a shared `idOf`) on each compiled stage, on the baseline's provision and on each step's sides. `TestRehearseRecordNamesTheRun` holds both children to them, and `TestRehearseEveryStagePasses`'s wire comparison covers them too. The replay tests pass. The run's checkpoint: `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` exit 0. The first run took 44.5 s wall at load 2.33 → 6.35, because it rebuilt every test binary below `internal/lab/wire`. The second took 37.3 s at load 5.92 → 5.06, with `internal/cli` 32.9 s, `internal/lab` 11.4 s and `internal/provision` 8.8 s. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `git diff --stat main -- testdata/golden` empty; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean. No task in this run names a tier-2 test, so none ran, and Infrahub was not touched. `make build` rewrote `bin/fylgja`, so the worker (`3867740`) and the server (`3867762`) still read `(deleted)`. Neither was restarted: the worker is not this run's to stop, and the server waits for T050. Until then the running worker writes `twin.json` `8`.

- [X] T019 [P] [US6] The findings blocks in `internal/findings/render.go` (data-model §5.3):
  - `Document.SnapshotID string` (`json:"snapshot_id,omitempty"`), placed beside `BundleID`;
  - `Subject.Snapshot string` (`json:"snapshot,omitempty"`; this file's decision, header);
  - `PlanStage.SnapshotID *string` (`json:"snapshot_id"`, null when nil);
  - `RehearsalStage.SnapshotID *string` (`json:"snapshot_id"`);
  - `ShowRecord.SnapshotID *string` (`json:"snapshot_id"`);
  - the step blocks' side type and `ShowStep`'s sides `SnapshotID string` (`omitempty`);
  - `ShowRecord.Source`'s comment names `snapshot`.

  Update every constructor and test helper that builds these, so the tree compiles with nil or `""` where nothing yet sets an id.

  - *2026-10-27, Run 7, the converge loop's session, at `4c52786`:* **done.** The seven fields are in `internal/findings/render.go` as the task lists them, each beside its bundle: `Document.SnapshotID` and `Subject.Snapshot` omitted when empty, `PlanStage`, `RehearsalStage` and `ShowRecord` written as `null` when nil, and `StepSideBlock.SnapshotID` (the type both the step block and `ShowStep` use for their sides) omitted when empty. `Document` and `ShowRecord` take trailing comments rather than comment lines, so gofmt does not realign either block. The tree compiled with every constructor unchanged, since a nil pointer and an empty string are the zero values. One constructor already had the id to hand: `provision.StepBlockOf`'s side now copies `wire.StepSide.SnapshotID`, which T016 added, so a step's document names a side's snapshot as soon as T042 sets it. `stages.PlanStage.Block` and the server's step sides stay without one until T040 and T042 give them an id. The show record and its sides are T022's, and the rehearsal stage T021's.

- [X] T020 [US6] The five moved contracts and their frozen copies (formats.md §3–§7, §9). **Freeze first.** Copy `contracts/findings.schema.json`, `show.schema.json`, `stages.schema.json`, `step.schema.json` and `rehearsal.schema.json` byte for byte to `internal/findings/testdata/contracts/017-dcim-reader/`, `internal/server/testdata/contracts/017-dcim-reader/` and `internal/cli/testdata/contracts/017-dcim-reader/` (15 files). Then edit the contracts as formats.md gives them, quoting its descriptions:
  - `findings.schema.json`: top-level optional `snapshot_id`; `subject.snapshot` an optional string; `dry_run.follow.reason` gains `snapshot`; the 018 sentence in the description.
  - `show.schema.json`: `record.snapshot_id` required, string or null; `record.source` gains `snapshot`; `record.step` sides gain an optional `snapshot_id`.
  - `stages.schema.json`: `plan_stage.snapshot_id` required, string or null.
  - `step.schema.json`: `side.snapshot_id` optional.
  - `rehearsal.schema.json`: `stage.snapshot_id` required, string or null; the description names the markdown's `snapshot` column.

  Then the tests:
  - Set `frozenContractCopies` in `internal/findings/frozen_contracts_test.go` to the count the glob finds: 33 + 16 = 49, unless T016's and these copies say otherwise. Record the count.
  - Each package's additivity test (the one that loads a frozen findings contract beside today's, in `internal/findings`, `internal/server` and `internal/cli`) gains the `017-dcim-reader` case. Read the existing cases for the pattern: a document of a twin with no snapshot (a `twin provision`'s, a `stage list`'s) validates under both.
  - Every document test in those packages that validates against today's contracts passes with the new required keys. Fix the builders, not the schemas.

  - *2026-10-27, Run 7, the converge loop's session, at `4c52786`:* **done.** `git log -1` names 017's commits for `findings` (`64e2272`), `show` (`f157574`) and `rehearsal` (`b112d87`), and `fc709ed`, the Release 0.2 hygiene commit, for `stages` and `step`, so all five are frozen under `017-dcim-reader/`, as this file's header decides. The 15 copies are `cmp`-equal to the contracts as they stood before the edits. The glob now finds **49** copies, and `frozenContractCopies` is 49. The contracts follow formats.md §3–§7, quoting its descriptions for each new key. `subject.snapshot` is an optional string, as this file decided. `stages.schema.json` gains an 018 sentence too, though formats.md §5 does not ask for one, as every other moved schema has one. `subject.ctm` is unchanged: `twin compile --ctm` still writes it until T036. 017's findings contract refers to `verify.schema.json`, which 018 does not move and so is not frozen. Each package's contract loader therefore reads a block that the feature's directory lacks, but that its findings contract refers to, from `contracts/`. The block had not moved since that feature. The tests:
    - `internal/findings`: `TestA017DocumentIsUnchanged` validates every document set the package builds (M2's to 017's, the stages', the step's, the rehearsal's and verify's: 66 documents) under 017's copy, with the null ids taken out, and under the current contract as built. `TestSnapshotBlocksSatisfyTheContract` builds seven documents that name a snapshot: a compile, a create's dry run from `--snapshot` (follow reason `snapshot`), a plan, a step, a rehearsal, a show of a snapshot twin, and a show of a stepped record. The current contract accepts each and 017's refuses each. It also pins each key's place in the JSON, and holds ten refusals of the current contract: a malformed id at each place, a required key left out, and an unknown follow reason.
    - `internal/server` and `internal/cli`: `validateM10Document`, which every document test in both packages calls, now also validates any document that names no snapshot against 017's copy, with the null ids taken out. So the additivity case covers every document these packages build, not one example.
    - The older contracts' helpers (`asEarlier` in `internal/findings`, `asEarlierContract` in `internal/cli`) take the null ids out first. The ids are always written from 018, and every pre-018 contract forbids the key. A set id is left in, so an older contract still refuses a document that names one.
    - Two pinned key strings in `TestStageListAndPlanSatisfySchema` gain `"snapshot_id":null`. No builder needed a fix and no schema was loosened.

- [X] T021 [US6] The rehearsal's table (R-14; formats.md §10). In `internal/rehearsal/markdown.go`, the header becomes `| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |`, and the separator gains a column. Each row's cell is `shortID(snapshot_id)` (eight characters and `…`, as the bundle's), or `—` when null. `rehearsal.Stage.SnapshotID string` in `internal/rehearsal/report.go` is carried into `findings.RehearsalStage.SnapshotID`. `fit`, its order of leaving parts out, the brief table and `CommentMax` stay unchanged. Update the pinned headers in `internal/rehearsal/markdown_test.go` (lines 47, 88, 648, 773) and `internal/cli/twin_rehearse_test.go` (line 1042). Add `TestSnapshotColumnBeforeBundle`, with a refused stage showing `—`. `TestCommentFitsTheLimit`, or its equivalent, still holds at the largest report the tests build. `rehearsal.steps.none` still judges by bundle equality: a test with two adjacent stages of one bundle id and two snapshot ids still raises it (US5 scenario 5).

  - *2026-10-27, Run 7, the converge loop's session, at `4c52786`:* **done.** The header and separator are R-14's. The snapshot cell is `short` of the id, the function the bundle's cell uses (the task's `shortID`), or `—`. `rehearsal.Stage.SnapshotID` reaches `findings.RehearsalStage.SnapshotID` in `Build`. `fit`, its order, the brief table and `CommentMax` are untouched, and `TestMarkdownFitsAComment` still passes at its 14- and 60-mark reports and its largest one, with each row a column wider. The test fixture's four compiled stages carry snapshot ids (`a1…`–`a4…`) apart from their bundles, so a row that swapped the two columns would fail. The 28 pinned rows in `markdown_test.go` and the pinned header in `twin_rehearse_test.go` gained the column. **Two departures:**
    - formats.md §10 and R-14 say `internal/checks` pins the header, but no file there does. Case 9 of `scripts/e2e.sh` does pin it, so its one `contains(…)` moved with the header, and shellcheck is clean. Otherwise tier 3 would fail against this build. The README's example table is T058's.
    - `rehearsal.steps.none` does not judge by bundle equality, here or in 015's contract. `contracts/cli.md` and `RuleRehearsalStepsNone`'s comment define it as "one stage alone compiled", and the server's `rehearsalStages` files it by count. So two adjacent compiled stages of one bundle never raised it, and the task's "still raises it" cannot hold. Spec US5 scenario 5 asks that it judge as before and that the two rows show their snapshot ids, and that is what is built. `TestSnapshotColumnBeforeBundle` gives the head third-link's bundle and its own snapshot. Their rows show `a2a2a2a2…` and `a4a4a4a4…` beside one `d0d0d0d0…`, both are rehearsed, and no `rehearsal.steps.none` is filed. The refused branch point shows `— | —` and carries `null` ids in the block. On the server, `TestRehearsalStagesTakeTheBaselineRule`'s plan already has third-link and head share one bundle with no warning. Its plan stages gain snapshot ids at T040.

- [X] T022 [US6] `twin show` reads the record (R-08; data-model §8). In `internal/server/show.go`:
  - `recordLine` becomes `record: <ref>, snapshot <id|none|none (record <v>)>, bundle_id <id>, schema <hash>, <provenance clause>`. The full id is printed. `none` is for a `9` naming none. `none (record <v>)` is for a record before `9`, naming its `twin_version`.
  - `ShowRecord.SnapshotID` is the record's (nil for an `8`), and the step sides carry their ids.
  - The kind and notes for `source: snapshot` are T034's.

  Update the pinned record lines in `internal/server` and `internal/cli` show tests. Add cases for a `9` with an id, a `9` naming none, and an `8`. `twin create`'s and `twin provision`'s closing record line is the same function: confirm both print it.

  - *2026-10-27, Run 7, the converge loop's session, at `4c52786`:* **done.** `recordLine` is `record: <ref>, <snapshot>, bundle_id <id>, schema <hash>, <provenance clause>`, and `snapshotClause` gives `snapshot <id>` (the full id), `snapshot none` for a `9` naming none, and `snapshot none (record <v>)` before `9` (`snapshotRecorded`, beside `scopeRecorded`). `ShowRecord.SnapshotID` is the record's pointer, nil for a `9` naming none and for an `8`, and `showStep`'s sides copy each side's id. The provenance clause is unchanged. `internal/server` pinned no record line, so `TestRecordLineNamesTheSnapshot` (new `internal/server/show_test.go`) covers a `9` with an id, a `9` naming none, an `8` and a `7`. `internal/cli`'s 17 pinned record lines gain the snapshot: `snapshot none` for a `9`, and, in the tests of earlier versions (2, 3, 4, 5, 7), a new `noSnapshot(version)` helper beside `unknownScope`. `readyResult`'s hand-built record moves from `8` to `9`, the version this build's worker writes, so the create's closing line reads `snapshot none`. `TestShowRecordNamesItsSnapshot` covers the task's three cases through the server: the line, the record's id or `null` in JSON, the document against the contract, and a stepped record whose sides and top level name their snapshots. Both commands print the line through `provisionReport` (`follow.go`): `TestCreateReadyPrintsTheTwin` pins the create's, and `TestProvisionNotFollowing` now pins the provision's, `snapshot none`, since a bundle's twin names none. The run's checkpoint: `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` exit 0, twice. The first run took 48.5 s wall at load 2.01 → 5.55, over the 45 s budget, because it rebuilt every test binary below `internal/findings`, as T008's and T018's first runs did. The second took 37.8 s at load 5.19 → 5.25, with `internal/cli` 33.4 s, `internal/lab` 11.5 s and `internal/provision` 8.9 s. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `git diff --stat main -- testdata/golden` empty; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean. No task in this run names a tier-2 test, so none ran, and Infrahub was not touched. `make build` rewrote `bin/fylgja`, so the worker (`3867740`) and the server (`3867762`) still read `(deleted)`. Neither was restarted: the worker is not this run's to stop, and the server waits for T050.

**Checkpoint**: `make test`, `make lint`; the nine histories replay; `twin show` names
`snapshot none` for every twin this tree can yet make.

---

## Phase 6: User Story 1 — A create the server takes a snapshot for (Priority: P1) 🎯 MVP

**Goal**: `twin create --branch` and `--stage` read, take, file, compile and file on the
server, and start the provision workflow with both ids, so the run begins at the host
check. The bundle's CTM sidecar is retired (FR-008–FR-010, FR-013, FR-014, SC-001; R-05,
R-09, R-11).

**Independent Test**: over the harness's fake Infrahub, a `twin create --branch` makes
these true: `snapshots/<id>.json` is filed; the bundle is filed with no `<id>.ctm.json`
beside it; the provision input the fake service receives carries `SnapshotID` and
`BundleID`; the answer prints the two `stored:` lines before `start`; a refused read
starts no run and files nothing.

- [X] T023 [US1] Retire the sidecar (FR-008; R-04, R-05).
  - `internal/bundle/store.go`: `Store` loses `PutCTM`, `DirStore` its implementation, and the type's comment drops the sidecar sentence (line 43).
  - `internal/provision/activities.go`: the `Compile` activity no longer calls `PutCTM` (line 258). It still removes the `.reads/` CTM it compiled. `ReadIntent` and `readsDir` are untouched.
  - `internal/server/filing.go`: `fileCompiled(ctx, dir, files, id)` loses its CTM parameter, and `keepCTM` goes.
  - `internal/stages/plan.go`: `Pipeline.File` and `NewPipeline`'s argument lose the CTM parameter, and the comments drop "and its CTM".
  - Fix every caller (`create.go`, `stages.go`, `step.go`, `rehearse.go`, the stages' fakes) and every test that asserted a sidecar.

  Add `TestNoSidecarIsWritten`: a dry run's filing, and the `Compile` activity over a test store, each leave no `*.ctm.json` beside the bundle. A sidecar placed in the store by hand before the filing is neither read nor removed. `grep -rn 'PutCTM\|\.ctm\.json' internal cmd` finds only `ReadIntent`'s `.reads/` path and comments that say the sidecar is retired.

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** `bundle.Store` loses `PutCTM` and `DirStore` its implementation; the type's comment says the sidecar is retired and that one an earlier build left is neither read nor removed. The `Compile` activity files the bundle alone and still removes the `.reads/` CTM it compiled; `ReadIntent` and `readsDir` are untouched. `fileCompiled(ctx, dir, files, id)`; `keepCTM` is gone, and with it the server's `writeCTM` in `read.go`, which nothing else used (T038's "if nothing else uses it" held already). `stages.Pipeline.File` and `NewPipeline`'s argument lose the CTM. Callers fixed: `create.go`, `stages.go`, `step.go` (`rehearse.go` files through `stages.go`'s plan and has no filing of its own), the stages' fake, the CLI harness's own `fileCompiled`, and `stages_contract_test.go`'s `filing`, which now keeps each filed bundle's CTM by wrapping the pipeline's `Compile`.
    - Tests that asserted a sidecar: `TestPutCTMOverwrites` is removed; `TestSidecarsDoNotAffectEntries` places one by hand; `TestCompileActivity` asserts none; the CLI's `storedBundles` asserts none beside any bundle. `TestStepRuns` read its target's `observed_at` from the sidecar; it now holds each run's `observed_at` inside the commands' span, the second's no earlier than the first's.
    - `TestNoSidecarIsWritten` is in `internal/provision` (the `Compile` activity) and `internal/server` (the dry run's filing), each with a sidecar placed by hand first, left byte for byte.
    - The grep finds, outside tests, the retirement comment in `internal/bundle/store.go` and `ReadIntent`'s `.reads/` path alone. In tests it finds `.reads/` paths, the input file names of the `--ctm` tests (T037's), and the assertions that no sidecar is written.
    - Tier 2: `TestStagesListAndPlan`, the one contract test whose `filing` changed, passed in 178.3 s (`go test -count=1 -tags contract -run '^TestStagesListAndPlan$' ./internal/stages`). Infrahub was left as the tier leaves it: `main` and `fylgja-fixture`, no proposed change, no stage.

- [X] T024 [US1] Create `internal/server/snapshot.go` (data-model §4; R-05, R-09).
  - `takeSnapshot(ctx, paths lab.Paths, step string, c *ctm.CTM) (s *snapshot.Snapshot, path string, list findings.List, err error)`. It calls `snapshot.Take`, then `snapshot.NewDirStore(paths.Snapshots).Put`. A `*snapshot.ErrIDMismatch` is `snapshot.id.mismatch` at `step`, naming the store path and both ids. Any other failure is an error the caller reports as `operation.failed`.
  - `snapshotStoredLine(id, path string) string` returns `snapshot_id <id>  stored: <path>`. The existing bundle line's function sits beside it, so the two are worded once.

  Tests in `internal/server/snapshot_test.go`: a take filed under its id; a second take of the same CTM (another `observed_at`) leaves the entry's bytes unchanged; a corrupt entry is `snapshot.id.mismatch` at the step given.

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** `takeSnapshot(ctx, paths, step, c) (*snapshot.Snapshot, string, findings.List, error)`: `snapshot.Take`, then `snapshot.NewDirStore(paths.Snapshots).Put`. A corrupt entry is one `snapshot.id.mismatch` at `step`, its object the store path, worded as the bundle store's (`store entry <path> hashes to <got>, not <want>, so snapshot <id> cannot be filed`), and no snapshot is returned, since none was filed. An entry that is no snapshot at all is the store's own error, which the caller reports as `operation.failed`. `snapshotStoredLine` and `bundleStoredLine` sit together in `snapshot.go`, and `dryRunReport` prints both through them. Tests in `internal/server/snapshot_test.go`: `TestTakeSnapshotFilesUnderItsID` (the entry is the take's stored form, `6a8a77fc…` for the fixture), `TestASecondTakeLeavesTheEntry`, `TestACorruptEntryIsSnapshotIDMismatch`.

- [X] T025 [US1] The create's live path on the server (R-11). In `internal/server/create.go`'s `runCreate`, after the stage's resolution and before any run starts, run these steps in order:
  1. the state root;
  2. `observedAt` captured;
  3. `stage.Read` under `stage.ReadTimeout`;
  4. `takeSnapshot` at `read`;
  5. `stage.Compile`;
  6. `fileCompiled`;
  7. the `snapshot_id … stored:` line, then the `bundle_id … stored:` line;
  8. `ProvisionInput{Source: intent, Branch, At, BundlePath, BundleID, ObservedAt, SnapshotID, Scope, Stage, Follow, StopFollowing: true}`.

  Each refusal is the document the command ends with, at `read` or `compile`, as `runCreateDryRun` places them, and no run starts. A refused read files nothing. A refused compile after a clean read leaves the snapshot filed (R-05; T004 (b)). An Infrahub that fails or times out during the read is `operation.failed` at `read`, at once. Factor the read-take-compile-file sequence into one function that `runCreate` and `runCreateDryRun` both call (D-011's one path), and set `Document.SnapshotID` on the answer once the take completed. The text: the two `stored:` lines print before the run's `start` event (snapshot-commands.md "The text").

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** `readTakeCompile` in `create.go` is the one path from a reference to a filed bundle. `runCreate` and `runCreateDryRun` both call it with `stage.Read`, passed as a `readFunc` so `internal/server`'s tier-1 tests can hand it a fake read. Its order is the task's: the state root, `observed_at`, the read (bounded by `stage.ReadTimeout` inside `stage.Read`), the take, the compile, the filing. A read that cannot run is `operation.failed` at `read`, naming `branch <b>`. A refused read files nothing. A refused compile's document names the snapshot.
    - **Decided here:** the stores' refusals are at `compile`, not `read`. The contract's Identifiers table (snapshot-commands.md; data-model §6) gives `snapshot.id.mismatch` the step `compile` for a corrupt store entry, as `bundle.id.mismatch` has. The run's compile step also filed the sidecar the snapshot replaces. So the create's take passes `compile`, and a snapshot filing that cannot run is `operation.failed` at `compile`, naming `snapshots/`. The task's "`takeSnapshot` at `read`" is kept as the order.
    - The run's input is `Source: intent, Branch, At, BundlePath, BundleID, ObservedAt` (the read's), `SnapshotID, Version, Scope, Stage, Follow`; `runProvision` sets `StopFollowing: true`, as before. `compiledRead.carried` puts what the server did on whatever document the run ends with, before `withStage`: `snapshot_id`; `bundle_id` when the run names none, as a start refusal's does (findings.schema.json: "any status once compile completed"); and the read's and the compile's findings, before the run's. The run no longer reports those findings, since it starts at the host check. The two stored lines print after the stage's line and before `run fylgja-provision …`.
    - **Tier 1's isolation:** the first run of `internal/cli` after this change read the operator's Infrahub from the session's environment. Those create tests set no address, and the harness's server took the session's `FYLGJA_STATE_ROOT`. It filed `local/snapshots/576933ec….json` on the host, which was removed again; the bundle `f764e1fa…` was already there. As observed, not a hand check: the live fixture's take is `576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482`, research §1.3's candidate. The CLI harness's `TestMain` now points `FYLGJA_STATE_ROOT` at a scratch directory and `INFRAHUB_ADDRESS` at `127.0.0.1:1` for every test that sets neither.

- [X] T026 [US1] The dry run (R-09). `runCreateDryRun`, now on T025's shared function, prints the `snapshot_id … stored:` line above the `bundle_id … stored:` line and sets `Document.SnapshotID`. `internal/server/dryrun.go`'s report is otherwise unchanged. Update the pinned dry-run outputs in `internal/server/dryrun_test.go` and `internal/cli/dryrun_test.go`. Also validate the dry run's document against `contracts/findings.schema.json` with `snapshot_id` present.

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** `dryRunReport` takes the filed snapshot (`*filedSnapshot`; nil for `twin provision`'s dry run), prints its stored line above the bundle's, and sets `Document.SnapshotID`; nothing else in the report moved. The pinned dry-run text is `internal/cli`'s `TestCreateDryRunFromAStage`, which now pins the snapshot's line and id. `internal/server/dryrun_test.go` calls the report with no snapshot and pins no stored line, so only its arguments changed. `TestCreateDryRunTakesTheSnapshot` (`internal/server`) runs the dry run on the create's path over a fake read, pins the four lines from `dry run:` to `bundle_id`, and validates the document against `contracts/findings.schema.json` with `snapshot_id` present.

- [X] T027 [US1] Tier-1 tests of the create, in `internal/server` (the server's tests over faked pipelines and service) and `internal/cli` (the harness's fake Infrahub, `harness_test.go`). These are US1 scenarios 1, 3, 4 and 5 and edge cases.
  - `TestCreateTakesTheSnapshotBeforeTheRun`: a `--branch` create files one snapshot and one bundle before the fake service's start; the `ProvisionInput` it receives carries both ids, `Source: intent` and a `BundleID` (so the workflow runs no read); the text holds the two `stored:` lines before `start`.
  - `TestCreateFromAStageTakesItsPinnedRead`: the record input names the stage, the snapshot and the bundle.
  - `TestRefusedReadStartsNothingAndFilesNothing`: a scope matching no device (`scope.empty`) or a device no package matches ends `rejected` at `read`; no run starts; `snapshots/` is absent or empty.
  - `TestRefusedCompileKeepsTheSnapshot`: a package the server lacks; the run does not start; the snapshot is filed.
  - `TestUnreachableInfrahubFailsTheCreateAtRead`: `operation.failed` at `read`, no run.
  - `TestCreateTwiceFilesOneSnapshot`.

  In `internal/cli`, the existing create tests' pinned text gains the two lines, and their documents validate.

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** In `internal/server` over a fake read: `TestRefusedCompileKeepsTheSnapshot` (a package the server lacks: rejected at compile, the snapshot filed and named, no bundle), `TestARefusedOrFailedReadFilesNothing`, `TestACreateOverACorruptSnapshotEntry` (`snapshot.id.mismatch` at compile, no ids, no bundle) and T026's test. In `internal/cli` over the fake Infrahub (`create_snapshot_test.go`): `TestCreateTakesTheSnapshotBeforeTheRun` (both files are on disk when the service is asked to start), `TestCreateFromAStageTakesItsPinnedRead` (the run, on the suite, records the stage, `6a8a77fc…` and `43d91715…`), `TestRefusedReadStartsNothingAndFilesNothing`, `TestUnreachableInfrahubFailsTheCreateAtRead` and `TestCreateTwiceFilesOneSnapshot`.
    - Two cases have no fake-Infrahub form. A read through the fake gives each device the package its platform matches, so no fake read carries a package the server lacks; the refused compile is therefore `internal/server`'s alone. The refused read is built on `scope.empty`; the task's other case, a device no package matches, is not built, since the fake serves a platform only from a known package, and it goes through the same refusal path at `read`.
    - The existing tests: each that reaches a run now serves the fixture (`useFixtureRead`), which touched 28 tests across 12 files. Their pinned text gains the two lines (`storedLines`). An unpinned read of the fake's fixture is `856af9ad…`/`951b7d21…`, with no `at` in its provenance; the fixture at its own `at` is `6a8a77fc…`/`43d91715…`. A document naming a snapshot is held to the current contract where it was held to M2's, M4's or M5's, which forbid the key; `wantStartRefusal` and the M2 step test choose by `namesSnapshot`. `TestCreateFromAStage` no longer asserts that the create reads no intent; it asserts that the read is pinned at the stage's `at` (`readsAtAlone`). `TestCreateCarriesItsScope`'s fake tags the fixture with each case's scope. `internal/cli` takes about 35 s alone.

- [X] T028 [US1] A following twin is unchanged (US1 scenario 6; FR-013). Read `internal/server/follow.go` and the check workflow's rebuild. The rebuild's `ProvisionInput` sets no `SnapshotID`, so its record names none. Add a tier-1 test (in `internal/provision` with the workflow test environment, or wherever the rebuild's input is built) that a rebuild's provision input has an empty `SnapshotID` and its record's `snapshot_id` is null. Check that `twin show` over such a record prints `snapshot none`. `bundles/.reads/` is still written by `ReadIntent` and removed by `Compile`.

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** The rebuild's `ProvisionInput` (`workflow_reconcile.go`, step 8) sets no `SnapshotID`, and nothing changed there. `TestARebuildNamesNoSnapshot` (`internal/provision`): the check compiles its own `bundles/.reads/` CTM; its provision child names no snapshot; that input, run through the provision workflow, reads and compiles nothing and gives the record step no snapshot. That `NewRecord` writes `"snapshot_id": null` for such an input is `internal/lab`'s `TestRecord9`, and that `twin show` prints `snapshot none` for it is `internal/server`'s `TestRecordLineNamesTheSnapshot`. `bundles/.reads/` is still written by `ReadIntent` and removed by `Compile` (`TestCompileActivity`).

- [X] T029 [US1] Redraw the C4 model in the same change (`CLAUDE.md`, "A changed package … is redrawn"; data-model §10). In `docs/c4/workspace.dsl`:
  - the relations `handlers -> snapshot "Takes, validates and files snapshots"` and `stages -> snapshot "Takes each stage's snapshot"` (the component and the store container are T011's);
  - the worker's `workflows` description saying the provision, step and rehearsal take a snapshot id and a bundle id and the reconcile alone reads;
  - the bundle store's description without the sidecar.

  Then `make diagrams`, and commit the regenerated views with the model.

  - *2026-10-27, Run 8, the converge loop's session, at `6d74a0c`:* **done.** In `workspace.dsl`: `handlers -> snapshot "Takes, validates and files snapshots"`; `stages -> snapshot "Takes each stage's snapshot"`, data-model §10's relation, which the code reaches at T040; the server's description takes and files each read's snapshot; the worker's `workflows` description says the provision, step and rehearsal take a snapshot id and a bundle id and the reconcile alone reads; the worker's reads of Infrahub and its `ReadIntent, Compile` edge name a following check's. The bundle store's description already named no sidecar. `make diagrams` redrew four views and their SVGs; the context view did not move. `scripts/diagrams.sh` added `internal_server --> internal_snapshot` to `docs/development.md`'s import graph.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`. The
MVP is in tier 1: every create the server starts is compiled, names its snapshot and
writes no sidecar.

---

## Phase 7: User Story 3 — A twin from a snapshot, frozen (Priority: P2)

**Goal**: `twin create --snapshot <id|file>` builds a twin from a stored or sent snapshot
with no read, frozen by rule (FR-015–FR-018; R-07, R-08, R-12).

**Independent Test**: in tier 1, these hold: `--snapshot <id>` of a stored snapshot starts
a provision with `Source: snapshot` and both ids, and the fake Infrahub receives no
request; an unknown id is `snapshot.unknown`; a mismatched file is `snapshot.id.mismatch`;
`--interval` and `--branch` beside it are refused before any connection; `twin show` over
the record reads `frozen; not following; built from snapshot <id8>…`.

- [X] T030 [US3] The guards, in `internal/server/create.go` and `snapshot.go`, before any connection (R-07).
  - `--branch or --stage or --snapshot is required` replaces today's required message. Update its pins.
  - `--snapshot` beside `--branch`, `--stage`, `--at` or `--scope` is `snapshot.flags.conflict` at `start`, exit 2, naming the first found in that order. Message: `--<flag> is meaningless with --snapshot: a snapshot carries its own branch, at and scope`.
  - `--interval` beside `--snapshot` is `follow.flags.conflict`: `--interval is meaningless with --snapshot: a twin built from a snapshot never follows`, through `followFlagsConflict`.
  - `--no-follow` and `--dry-run` are accepted. `createFollow` gives `FollowReasonSnapshot` for `--snapshot`, and the dry run's follow line reads `would not follow (--snapshot given: a twin built from a snapshot never follows)`.
  - `createFlags` gains `snapshot string`. `Subject.Snapshot` is set to the argument as given.

  - *2026-10-27, Run 9, the converge loop's session, at `3e26318`:* **done.** `createFlags` gains `snapshot` and `snapshotGiven`, and `fromSnapshot()` beside `fromStage()`. The required message is `--branch or --stage or --snapshot is required`; its two pins (`internal/cli`'s `connect_test.go` and `stage_create_test.go`) moved, and `intent read`'s stays. `snapshotGuards` in `snapshot.go` refuses `--branch`, `--stage`, `--at`, `--scope` in that order, then `--interval` through `followFlagsConflict`, which gains the `--snapshot` case first. "Given" is the stage guards' rule: a non-empty `--branch` or `--at`, `--stage` given whatever its value (`--stage=` is refused naming `--stage`), `--scope` given. `createFollow` gives `FollowReasonSnapshot` first, and the dry run's line reads `would not follow (--snapshot given: a twin built from a snapshot never follows)`. `Subject.Snapshot` is the argument as given.
    - **Decided here:** once the snapshot resolves, the subject's `branch` and `at` are the envelope's, as a stage's name the reference it resolved to; its `scope` stays unset, since the create reads under none (findings.schema.json's `subject.scope`: "absent on an operation that reads under none").

- [X] T031 [US3] `resolveSnapshot` in `internal/server/snapshot.go` (R-12), at `resolve`.
  - An argument that `snapshot.IsID`: `store.Fetch`. Absent is `snapshot.unknown`, exit 1, at the id: `the store under <dir> holds no snapshot <id>; a snapshot id comes from a create, a dry run, a plan or intent read --out on this server`. A corrupt entry is `snapshot.id.mismatch` naming the store path.
  - Otherwise the request's one file under that path: `snapshot.Unmarshal`. Each error type maps to its rule, at `resolve`, object the file or the field: `*VersionError` → `snapshot.version.unsupported`; `*InvalidError` → `snapshot.invalid` at its field; `*ctm.VersionError` → `ctm.version.unsupported`; `*ctm.MissingError` → `data.required.missing` at its prefixed field; `*IDMismatchError` → `snapshot.id.mismatch`. Then `store.Put`, which keeps an entry already there; the twin then records the stored document's `observed_at`, via `Fetch` after `Put` (US3 scenario 8).
  - Then T025's compile and filing; `Document.SnapshotID` set; the two `stored:` lines.
  - Then `ProvisionInput{Source: snapshot, Branch: env.Branch, At: env.At, BundlePath, BundleID, ObservedAt: the stored document's, SnapshotID, Scope: env.Scope, Stage: nil, Follow: nil, StopFollowing: true}`.

  No request reaches Infrahub: build no intent client on this path. `--dry-run` reports as a create's dry run, with no read and no start.

  - *2026-10-27, Run 9, the converge loop's session, at `3e26318`:* **done.** `resolveSnapshot(ctx, paths, op, subject, arg, files)` in `snapshot.go`. An id: `Fetch`; absent is `snapshot.unknown` at `resolve` with the task's message; a corrupt entry `snapshot.id.mismatch` at `resolve` naming the store path (`store entry <path> hashes to <got>, not <id>, so snapshot <id> cannot be read`, the take's wording through a shared `corruptEntry`). A file: `snapshot.Unmarshal`, its refusals mapped by `snapshotRefusal(path, err)` (no step; the caller places it, so T036 reuses it), then `Put`, then `Fetch`, so the twin records the stored document's `observed_at`. `ctm.version.unsupported`'s message is `ctmVersionMessage`, now shared with `twin compile`. A file that is not JSON is `operation.failed` at `resolve` naming the file, as `twin compile` fails one: nothing was validated. Then `compiledRead.compileAndFile`, factored out of `readTakeCompile` so both creates compile and file on one path, the two stored lines, and `ProvisionInput{Source: snapshot, Branch, At, Scope: the envelope's, BundlePath, BundleID, ObservedAt: the stored document's, SnapshotID, Version}`; `runProvision` sets `StopFollowing`. Nothing on the path builds an intent client.
    - **Decided here:** (a) the packages load before the snapshot resolves, and an override refused is refused at `compile`, the first step that reads them, as a branch create's is refused at `read` before its stage resolves. (b) A corrupt entry met by the file's `Put` is at `resolve` with the rest of `resolveSnapshot`: data-model §4 gives this row `resolve` for `snapshot.id.mismatch`, and Run 8's "`compile` for the store" is the read's take, which stands where the run's compile filed the sidecar. (c) The dry run has no `read:` line, since nothing was read (as `twin provision`'s dry run); it prints the two stored lines, the nodes and the follow line, and files the bundle.

- [X] T032 [US3] The API (data-model §7; formats.md §8).
  - `internal/server/handlers.go`: `twin.create` accepts the argument `snapshot` and at most one file, only beside `snapshot` and only under the path it gives. A file beside no `snapshot`, two files, or one under another path is refused before anything is parsed: `operation.failed`, exit 2, `the request carries 1 file where twin create takes a snapshot file beside --snapshot alone`, through `checkFiles` and `checkRequired`.
  - `contracts/api.schema.json`: `$defs.args.twin.create.properties.snapshot`, and the `files` description sentence for `twin.create`.
  - `internal/api/wire_test.go`: the `twin.create` case with `snapshot`.
  - `internal/api`'s request types, if they list arguments.

  An earlier client's `--branch` create is answered as before (US6 scenario 4): an existing request fixture still passes.

  - *2026-10-27, Run 9, the converge loop's session, at `3e26318`:* **done.** `operationArgs` gives `twin.create` the string `snapshot`, and the handler passes it, `snapshotGiven` and the request's files to `runCreate`. `takesFiles` gains `twin.create`, so `checkFiles` lets a create's file through, and the create holds it to its shape itself (`snapshotFiles`, first in `runCreate`), as `twin compile` holds its CTM: the task's `operation.failed`, exit 2, is a document, which `checkFiles`' and `checkRequired`'s refusals, `400`, are not, and api.md's "as `twin.compile`'s are" settles it. The sentences: `the request carries 1 file where twin create takes a snapshot file beside --snapshot alone` (a file beside no `--snapshot` or beside an id, or two files, counted); `the request carries no file where twin create takes the snapshot file --snapshot names, under that path`; and, for one under another path, `twin compile`'s sentence for the same fault, worded for the snapshot. `contracts/api.schema.json`: `twin.create.properties.snapshot` as formats.md §8 gives it, and the files sentence `twin.create: the snapshot, under the path snapshot gives, when snapshot is a path (018).`; `twin.compile`'s sentence is T036's. `internal/api` lists no arguments. `wire_test.go` gains two `twin.create` cases (a file and an id) beside the earlier client's, which still passes; `server_test.go` holds that the transport answers `200` to a create carrying a file.

- [X] T033 [US3] The client (R-07). In `internal/cli/create.go`, `--snapshot <id|file>`, with help text naming both forms. An argument of 64 lowercase hex characters is sent as `args.snapshot`. Anything else is read whole by a `readSnapshot(path) (api.File, error)` in `internal/cli/files.go`, which replaces `readCTM` there and is worded `reading snapshot: …`. The file is sent as the request's one file under that path, with `args.snapshot` the path. A file the client cannot read is its own `operation.failed`, exit 2, before any connection. The client checks no flag combination: every guard is the server's (XI).

  - *2026-10-27, Run 9, the converge loop's session, at `3e26318`:* **done.** `--snapshot` with help naming both forms; `snapshotGiven` from `Changed`; `--branch`'s help says `this, --stage or --snapshot is required`. An id is sent as `args.snapshot`; anything else is read by `readSnapshot` and sent as the one file under that path; an unreadable file is the client's `operation.failed`, `reading snapshot: open <path>: no such file or directory`, and no request is sent.
    - **Left for T037:** `readSnapshot` sits beside `readCTM`, which `twin compile --ctm` still calls; T037 moves the compile to `--snapshot` and removes `readCTM`, which completes "replaces `readCTM`".
    - **Decided here:** the client tells an id by `isSnapshotID`, written in `create.go` and held to `snapshot.IsID` by `TestSnapshotIDShapeIsTheCoresOwn`, as its defaults are held to the core's (`defaults_test.go`): the client keeps importing `api`, `findings` and `tree` alone, so `docs/development.md`'s import graph and the C4 model do not move.

- [X] T034 [US3] `twin show` for a snapshot twin (R-08; FR-017). In `internal/server/show.go`, a record whose `source` is `snapshot` is decided by its envelope and never as following:
  - with an `at`: `kind: pinned at <T>; not following; built from snapshot <id8>…`;
  - without: `kind: frozen; not following; built from snapshot <id8>…`.

  Its block kind is `pinned` or `frozen`. The note `built from snapshot <id>`, with the full id, joins `notes`. The following branch of the kind table is not taken for it, whatever Schedule exists. `from a bundle` stays the kind for a record with no envelope. `twin step` against such a record is refused by the existing `step.twin.unsteppable` guard, since the record names no stage. Confirm with a test; its message names the record's branch as today.

  - *2026-10-27, Run 9, the converge loop's session, at `3e26318`:* **done.** A `case rec.Source == wire.SourceSnapshot` after the diverged case and before the pinned one in `decideShow`: with an `at`, `pinned`, `pinned at <T>; not following; built from snapshot <id8>…`, noting `pinned at <T>; not following`; without, `frozen`, `frozen; not following; built from snapshot <id8>…`, noting `not following`. Then the note `built from snapshot <id>` in full. The following case is never reached for it, whatever Schedule exists, and "not following" holds whether or not the service answers. `from a bundle` is untouched.
    - **Decided here:** "by the existing rules" (FR-017) is kept for the rest: a frozen snapshot twin keeps the frozen rule's best-effort note, and the record block keeps its `reproducing it with --at that instant is best-effort` clause, as any frozen twin's.
    - The step refusal needed no change: `provision.Ineligible` refuses a record naming no stage, `the twin was created from branch change-1 at …, not from a stage, …` (`origin` names the record's branch), shown by `TestStepFromSnapshotTwinIsUnsteppable`.

- [X] T035 [US3] Tier-1 tests (US3 scenarios 1–8), in `internal/server` and `internal/cli`.
  - `TestCreateFromAStoredSnapshot`: the fake Infrahub counts zero requests; the input is `Source: snapshot` with both ids and no `Follow`.
  - `TestCreateFromAnUnknownSnapshot` (`snapshot.unknown`, exit 1, `resolve`).
  - `TestCreateFromAMismatchedFile` (`snapshot.id.mismatch` naming both ids).
  - `TestCreateFromAFileWithNoID`: computed and filed.
  - `TestCreateFromAFileOfAStoredSnapshotKeepsTheFirstTake`: the input's `ObservedAt` is the stored document's.
  - `TestSnapshotFlagConflicts`: `--branch`, `--stage`, `--at` and `--scope` each give `snapshot.flags.conflict` naming it, the first found when two are given; `--interval` gives `follow.flags.conflict`; `--no-follow` is accepted; all of this before any connection, which the harness counts.
  - `TestUnreadableSnapshotFileIsTheClients`.
  - `TestShowSnapshotTwin`: with and without `at`; the note.
  - `TestStepFromSnapshotTwinIsUnsteppable`.

  Each document validates against `contracts/findings.schema.json`.

  - *2026-10-27, Run 9, the converge loop's session, at `3e26318`:* **done.** In `internal/cli/create_from_snapshot_test.go`, over the harness: `TestCreateFromAStoredSnapshot` (the fake Infrahub asked nothing; the two stored lines before `run`; the input `Source: snapshot`, both ids, the envelope's branch, `at` and scope, the stored `observed_at`, no `Follow`, no `Stage`; the run on the suite records source `snapshot`, the snapshot and the bundle), `TestCreateFromAnUnknownSnapshot`, `TestCreateFromAMismatchedFile`, `TestCreateFromAFileWithNoID`, `TestCreateFromAFileOfAStoredSnapshotKeepsTheFirstTake`, `TestCreateDryRunFromASnapshot` (with and without `--no-follow`), `TestSnapshotFlagConflicts` (each flag, the first of two, `--interval` alone, with `--no-follow` and with `--branch`; for an id and for a file; nothing dialled, Infrahub not asked, one server refusal logged), `TestUnreadableSnapshotFileIsTheClients` (no request logged), `TestShowSnapshotTwin` (with and without `at`, beside a Schedule of the twin's branch), `TestStepFromSnapshotTwinIsUnsteppable` and `TestSnapshotIDShapeIsTheCoresOwn`. In `internal/server`: `TestResolveSnapshotRefusesAFileByItsRules` (another version, a bare CTM, a probe, an inner CTM `1`, no fidelity list, a declared id mismatched, not JSON; nothing filed), `TestResolveSnapshotByID`, `TestResolveSnapshotFilesAFile`, `TestACreatesFilesAreOneSnapshotFile`, and `TestDryRunFollowCreate`'s two `--snapshot` cases. Every document validates against the current contract. A mutation of `decideShow`'s new case fails `TestShowSnapshotTwin`. No tier-2 test is named by these tasks, and none reaches the create, so none was run.

**Checkpoint**: `make test`, `make lint`.

---

## Phase 8: User Story 4, part 2 — the hand tools read and write snapshots (Priority: P2)

**Goal**: `twin compile --snapshot` in place of `--ctm`, and `intent read --out` writing
and filing a snapshot (FR-019, FR-020; R-07, R-09).

**Independent Test**: these hold in tier 1. `twin compile --snapshot
testdata/snapshot/three-node.json` answers `43d91715…` and files nothing. `twin compile
--ctm` is `unknown flag: --ctm`, exit 2, with no request. `intent read --out` over the
fake Infrahub writes a snapshot `1`, and the store holds it byte for byte.

- [X] T036 [US4] `twin compile --snapshot` on the server. In `internal/server/compile.go`'s `runCompile`: the argument `snapshot` replaces `ctm`, and the one file is read under the path it gives, through `snapshot.Unmarshal`, its errors mapped to their rules as in T031 but with no step (R-03). Then `stage.Compile` of its CTM, as today. On ok, `Document.SnapshotID` is the computed id. `Subject.Snapshot` is set, and `Subject.CTM` no longer. The text is `wrote bundle to <dir> (<n> nodes, <m> links)`, then `snapshot_id <id>`, then `bundle_id <id>`. Nothing is filed and no state root is needed. In `handlers.go`, `twin.compile` takes `snapshot` and `out`, and exactly one file under `args.snapshot`. A request carrying `ctm` is `400`, `the request is not one: twin.compile takes no argument "ctm"`. In `contracts/api.schema.json`, `twin.compile`'s `ctm` is renamed `snapshot` in `properties`, and the `files` sentence is updated. `internal/api/wire_test.go`'s `twin.compile` case changes to match.

  - *2026-10-27, Run 10, the converge loop's session, at `8035825`:* **done.** `runCompile` takes `snapshotPath`: `--snapshot is required`; one file under that path, or `the request carries %d files where twin compile takes the snapshot alone`, or the other-path sentence worded for the snapshot; then `snapshot.Unmarshal`, its refusals through T031's `snapshotRefusal` with no step; a file that is not JSON, or whose CTM does not decode, is `operation.failed`, as an unreadable CTM was. Then `stage.Compile` of `s.CTM`. The text is `wrote bundle to <dir> (<n> nodes, <m> links)`, `snapshot_id <id>`, `bundle_id <id>`. `Document.SnapshotID` is set on ok alone (findings.schema.json: "twin.compile (status ok)"); `Subject.Snapshot` is the argument, `Subject.CTM` unset. No state root is read. `operationArgs` gives `twin.compile` `snapshot` and `out`, so a request carrying `ctm` is `checkArgs`' `400`, `the request is not one: twin.compile takes no argument "ctm"` (a row of `TestAnArgumentNotTakenIsUnreadable`). `contracts/api.schema.json`: `twin.compile.properties.snapshot`, described, in place of `ctm`, and the files sentence `twin.compile: the snapshot, under the path given (018; the CTM before it).` `wire_test.go`: the `twin.compile` case sends a snapshot under `snapshot`, and `{"ctm": …}` is not `twin.compile`'s args.
    - Tests in `internal/server`: T035's refusal table is factored as `fileRefusals`, which `TestResolveSnapshotRefusesAFileByItsRules` and the new `TestCompileRefusesASnapshotByItsRules` (`compile_test.go`) both run: each refusal under its rule with no step, no ids, the state root left empty, the document valid. `TestCompileNamesTheSnapshotAndFilesNothing`: the three lines, and a file declaring neither `snapshot_id` nor `observed_at` compiling to `6a8a77fc…`/`43d91715…`. `TestACompileWithoutOneCTMIsRefused` is `TestACompileWithoutOneSnapshotIsRefused`.

- [X] T037 [US4] `twin compile --snapshot` in the client. In `internal/cli/compile.go`: the flag `--snapshot <file>` (required) replaces `--ctm`, and the short and long help name a snapshot and say a bare CTM is wrapped as `{"snapshot_version": "1", "ctm": …, "probes": []}`. The file is sent through `readSnapshot`, and `--ctm` is gone, so cobra answers `unknown flag: --ctm` with exit 2 and no request. Rewrite `internal/cli/compile_test.go`:
  - each wrapped fixture compiles to its golden, and the state root's `snapshots/` stays absent;
  - a hand-wrapped bare CTM with no `snapshot_id` and no `observed_at` compiles (US4 scenario 3);
  - a bare CTM is `snapshot.version.unsupported`;
  - a wrapped CTM `1` is `ctm.version.unsupported`;
  - `--ctm` is unknown, and the harness sees no request;
  - the help text names `--snapshot`.

  Update any other test or fixture under `internal/` that runs `twin compile --ctm`: `grep -rn -- '--ctm\|"ctm"' internal cmd`.

  - *2026-10-27, Run 10, the converge loop's session, at `8035825`:* **done.** `--snapshot <file>` replaces `--ctm`; the short help says a snapshot file, and the long one says a snapshot is what `intent read --out` writes and that a bare CTM is wrapped as `{"snapshot_version": "1", "ctm": <the CTM>, "probes": []}`. The file goes through `readSnapshot`, and `readCTM` is removed, which completes T033's "replaces `readCTM`". In `compile_test.go`: `TestWrappedFixturesComeBackAsTheGoldenBundles` (the three, byte for byte, each naming its file's snapshot id, `snapshots/` absent), `TestAHandWrappedCTMCompiles`, `TestCompileReadsASnapshotByItsRules` (a bare CTM, `snapshot.version.unsupported`; a wrapped CTM `1`, `ctm.version.unsupported`; each at the file, no step, no id), `TestCompileTakesNoCTM` (cobra's `unknown flag: --ctm`, exit 2, no request logged; the help names `--snapshot` and the wrap, and not `--ctm`) and `TestUnreadableSnapshotIsAnOperationalFailure`.
    - The other tests: each compile of a golden fixture compiles `testdata/snapshot/<name>.json` (`wrappedFixture`); each of any other CTM wraps it by the contract's recipe (`wrappedCTM`, `wrappedCTMOf`), in twelve other test files of `internal/cli`. A missing inner field is named under `ctm.` (`TestCompileRefusesACTMLeavingOutARequiredField`); a version or a validation refusal is named as before, at the snapshot file. `server/rehearse_contract_test.go`'s read-then-compile sends `snapshot.json` under `snapshot`. The grep finds `--ctm` in the comments that say it is retired and in `TestCompileTakesNoCTM` alone; `scripts/e2e.sh` line 529 still runs `twin compile --ctm`, T047's.
    - **Decided here:** `TestM1DocumentsStillSatisfyM1Schema`. A `twin compile` document now names its snapshot (`subject.snapshot`, and `snapshot_id` once compiled), which M1's contract, closed to keys it does not hold, forbids. It is held to the current contract, as Run 8 held a create's document naming one (`namesSnapshot`), and each case says whether it names one, so none is skipped silently. A compile document naming none (`--snapshot is required`) is still held to M1's.

- [X] T038 [US4] `intent read --out` writes and files a snapshot (R-09; FR-020). In `internal/server/read.go`, after a clean read: `takeSnapshot` (no step), and the files frame carries `snapshot.json` (`ctmFile` renamed `snapshotFile = "snapshot.json"`), its bytes `snapshot.Marshal`'s. `Document.SnapshotID` is set. The summary line ends `; snapshot <id>, stored at <path>`, after its parenthesis, as snapshot-commands.md "The text" gives it, and the same for a stage's read. `writeCTM` goes if nothing else uses it. A refused read has no files frame and files nothing. In `internal/cli/read.go`: the help and the `--out` flag say a snapshot file; the answer's one file is written atomically by a `writeSnapshot` in `files.go`, which replaces `writeCTM`; the guard reads `the answer carries %d files where intent read sends the snapshot alone`. `internal/api/wire.go` line 398's comment names `snapshot.json`.

  - *2026-10-27, Run 10, the converge loop's session, at `8035825`:* **done.** `read` reads through a `readFunc` (`runRead` passes `stage.Read`, a tier-1 test its own). After a clean read, `takeSnapshot(ctx, paths, "", c)`; the files frame carries `snapshot.json`, `snapshot.Marshal`'s bytes of this take (the store keeps a first take's entry); `Document.SnapshotID`; the summary line ends `; snapshot <id>, stored at <path>` (`snapshotSummary`), for a stage's read as for a branch's. A refused read, or one that could not run, sends no file and files nothing. A corrupt entry under the id is `snapshot.id.mismatch` with no step, naming the store path, and nothing is sent. `writeCTM` was already gone (Run 8). Client: the long help and `--out` say a snapshot file; `writeSnapshot` replaces `writeCTM` (`writing snapshot: …`, temporary `.fylgja-snapshot-*`); the guard reads `the answer carries %d files where intent read sends the snapshot alone`. `wire.go`'s comment names `snapshot.json`, and `call.files`' names the snapshot.
    - **Decided here:** the state root is resolved before the read, as the create's is (T025, step 1), so a read whose snapshot could not be filed is never made; a state root that cannot be resolved is the read's `operation.failed`.

- [X] T039 [US4] Tier-1 tests of `intent read` (US4 scenario 2), in `internal/server/read_test.go` and `internal/cli/intent_test.go` over the fake Infrahub.
  - The file is a snapshot `1` that `snapshot.Unmarshal` accepts.
  - `snapshots/<id>.json` equals the file byte for byte.
  - A second read, with another `observed_at`, writes a file differing only in its two `observed_at` lines, and leaves the store's entry unchanged.
  - The summary line ends with the id and the path.
  - The document's `snapshot_id` validates against the contract.

  Update `internal/cli`'s pinned summary lines. `grep -rn 'ctm.json' internal cmd` finds no product use but `.reads/`.

  - *2026-10-27, Run 10, the converge loop's session, at `8035825`:* **done.** In `internal/server/read_test.go`, over a fake read: `TestReadWritesAndFilesTheSnapshot` (the one file `snapshot.json`, sent before the line, a snapshot `1` `snapshot.Unmarshal` accepts, `6a8a77fc…`; the entry equal to it byte for byte; the line exactly `readSummaryLine` and the suffix; the document valid with the id; a second read, observed later, differs in its two `observed_at` lines alone and leaves the entry), `TestARefusedReadSendsAndFilesNothing` (refused and failed) and `TestAReadOverACorruptSnapshotEntry`. Sending `ctm.Marshal`'s bytes in place of the snapshot's fails the first, checked by mutation. In `internal/cli`, over the fake Infrahub: `TestReadWritesAndFilesASnapshot`, the same five checks through the client (`856af9ad…`, the fake's unpinned head) with the document validated by `validateM10Document`. `TestReadFromAStageIsThePinnedRead` pins the line with the snapshot and reads each `--out` as a snapshot; `stage_test.go`'s four read tests are the snapshot's, the refused one asserting nothing filed. Each `--out` a test names is `snapshot.json`.
    - The grep finds, outside tests, `ReadIntent`'s `.reads/<run id>.ctm.json`, `bundle.Store`'s retirement comment and `snapshotFile`'s comment. In tests: `.reads/` paths, sidecars placed by hand, the 400 row's `ctm.json`, and `findings`' documents of earlier shapes.
    - Tier 2: `TestRehearseComposedByTheFixtureTool`, the one contract test whose code changed (its read-then-compile through the server now sends and compiles the snapshot), passed in 121.3 s (`go test -count=1 -tags contract -run '^TestRehearseComposedByTheFixtureTool$' ./internal/server`). Infrahub was left as the tier leaves it: `main` and `fylgja-fixture`, no proposed change, no stage, no thread.

**Checkpoint**: `make test`, `make lint`; `--ctm` is gone from every command and test.

---

## Phase 9: User Story 5 — Stages, steps and rehearsals name the snapshot (Priority: P2)

**Goal**: the stages' pipeline takes each stage's snapshot; `stage plan`, `twin step` and
`twin rehearse` carry it into their rows, sides and report (FR-011, FR-012, FR-022,
FR-024; R-13).

**Independent Test**: in tier 1 over the stages' fakes: a plan of two stages names two
snapshot ids beside two bundle ids, and a stage refused at read names `null`; a step's
input and record name the from side's snapshot and the to side's; a rehearsal's stages and
the baseline's provision input carry their ids.

- [X] T040 [US5] The pipeline (data-model §4). In `internal/stages/plan.go`, add `Pipeline.Take func(ctx context.Context, c *ctm.CTM) (id string, list findings.List, err error)`. `NewPipeline(take, file)` takes it beside `File`. `build` calls `p.Take` after a clean read and before the compile: a rejection is the stage's at `read`, and an error is `PlanFailed`. Add `PlanStage.SnapshotID string`, set once filed and `""` when refused before it, with a `SnapshotID()` accessor beside `BundleID()`. In `internal/stages/blocks.go`, `PlanStage.Block` writes `SnapshotID` as a `*string` (nil when `""`). The server's pipeline (`stages.go`, `step.go`, `rehearse.go`) passes a `take` that wraps `takeSnapshot` with its paths. The stages' tier-1 fakes gain a `Take`, which takes a real `snapshot.Take` with no store or records calls. Assert in `internal/stages`' plan tests: the order is read, take, compile, file; a refused read calls no `Take`; `SnapshotID` is set on a compiled stage.

  - *2026-10-27, Run 11, the converge loop's session, at `00e81f1`:* **done.** `Pipeline.Take func(ctx, c *ctm.CTM) (id string, list findings.List, err error)`; `NewPipeline(take, file)`. `build` calls it after a clean read and before the compile, sets `PlanStage.SnapshotID`, and `PlanStage.Block` writes it as `*string`, null when `""`. A compile or a filing refused after the take leaves the id set, the snapshot filed (R-05). The server's one `stagePipeline(paths)` in `stages.go` wraps `takeSnapshot` and the dry run's filing; `planStages` (so `stage plan` and `twin rehearse`) and `twin step`'s build of its target use it, so a stage's ids are one whichever command built it (D-011). The stages' fake takes with a real `snapshot.Take`, no store, and records every call. Tests: `TestPlanTakesEachReadBeforeItsCompile` (read, take, compile, file per stage; the branch point's refused read takes nothing; `Build` the same, with the plan's id); `TestPlanStages` (an id per compiled stage, the taken ones, two ats of one intent two snapshots; the branch point `""` and null in its block); `TestPlanPerStageOutcomes` gains a take refused and a take that could not run, and asserts which outcomes keep the id. `stages_contract_test.go`'s `filing` takes into a store under the test's temporary directory.
    - **Decided here, as T025 did for the create:** the take's refusal (`snapshot.id.mismatch`, a corrupt entry) and a take that could not run are at `compile`, not `read` as the task's text says. The contract's Identifiers table (snapshot-commands.md; data-model §6) gives the store's mismatch the step `compile`, and the create places it there (`readTakeCompile`), so a stage and a create report one store fault alike.
    - **Decided here:** `PlanStage.SnapshotID` is a field and has no `SnapshotID()` accessor. Go refuses a field and a method of one name on one type, and data-model §4 names the field; `BundleID()` is a method only because the bundle is a pointer.
    - Tier 2: `TestStagesListAndPlan`, the one contract test whose code changed (`filing`), passed in 147.1 s (`go test -count=1 -tags contract -run '^TestStagesListAndPlan$' ./internal/stages`). Infrahub was left as the tier leaves it: `main` and `fylgja-fixture`, no proposed change, no stage, no thread.

- [X] T041 [US5] `stage plan`'s text and document. In `internal/server/stages.go`'s `printPlanned`, each compiled stage prints `  snapshot_id <id>` above `  bundle_id <id>`, then its read line as before. The plan document's `plan.stages[].snapshot_id` is the id or null. Update the pinned plan outputs in `internal/server` and `internal/cli` (`stage_plan_test.go`). Each plan document validates against `contracts/findings.schema.json` with `stages.schema.json`. A stage refused at the branch point (`scope.empty`) has `snapshot_id: null`. `stage list` is unchanged.

  - *2026-10-27, Run 11, the converge loop's session, at `00e81f1`:* **done.** `printPlanned` prints `  snapshot_id <id>` above `  bundle_id <id>` for each compiled stage. `TestStagePlanText` pins the three new lines; the branch point, refused `scope.empty` at its read, names `snapshot_id: null` and `bundle_id: null`; `snapshots/` holds exactly the three compiled stages' entries. Every plan document is validated by `validateM10Document` (the current findings contract with `stages.schema.json`; a document naming a snapshot is 018's alone). `internal/server` pins no plan text. `stage list` is unchanged.

- [X] T042 [US5] `twin step` (R-13; R-09).
  - In `internal/server/step.go`'s `stepInput`, `To.SnapshotID` comes from the built stage and `From.SnapshotID` from the record's `SnapshotID`, empty when nil (a record of `8`).
  - `Document.SnapshotID` is the target's, on the step and its dry run.
  - The step's twin line reads `twin: stage <s> (snapshot <id8>…, bundle <id8>…), pinned at …`, or `snapshot none` for a record naming none.
  - The step blocks' sides carry `snapshot_id`.

  Tests in `internal/server/step_test.go` and `internal/cli/twin_step_test.go`:
  - a step from a `9` record of stage A to stage B: the input's sides name A's snapshot and B's, and the record after `NewStepRecord` names B's at the top level and both in `step`;
  - a step from an `8` record: the from side has no `snapshot_id`, and the document validates against `step.schema.json`;
  - a diverged step keeps the previous record's top-level id.

  `step.twin.unsteppable` is unchanged.

  - *2026-10-27, Run 11, the converge loop's session, at `00e81f1`:* **done.** `stepInput`'s from side names the record's snapshot (`""` when nil) and its to side the one the target's build took. The step's twin line reads `twin: stage <s> (snapshot <id8>…, bundle <id8>…), pinned at …`, `snapshot none` for a record naming none (`shortSnapshot`). The dry run's document sets `snapshot_id`, and `provision.StepDocument` sets it for the run, as it sets `bundle_id`, from the to side (so `internal/provision` imports `internal/snapshot` for `IsID`; the C4 model draws none of the provision client's imports, nor `lab → snapshot`, so nothing is redrawn). The step blocks' sides already carried the id through `StepBlockOf` (T019).
    - The CLI's step fixture now records the from stage's snapshot as a create does: `compileStage` takes and files it through `NewPipeline(take, file)` and keeps it by bundle id (`snapshotOf`), `stepHost` and `twinAt` write it into the `9` record, and `stepDryRunLines` takes the fixture. The pinned twin lines move (`TestStepDryRun`, `TestStepBackToAnEarlierMark`, `TestStepFromTheBranchPointToTheHead`, `answer_test.go`); `TestStepRuns` and `TestStepBackToAnEarlierMark` compare whole sides with both ids; a twin of a bundle drops the snapshot, which `NewRecord` refuses for that source.
    - `TestStepNamesEachSidesSnapshot`, in `internal/cli`, whose fake Infrahub drives the server's step whole (`internal/server/step_test.go` has no fake Infrahub, so it gains no test): from a `9` record (sealed → again, unchanged), the twin line, the input's sides, and the document's id and step block; `lab.NewStepRecord` over that input names the target's id at the top level and both in `step`, and a diverged step keeps the record's own. From an `8` record (`unsnapshotted`), the twin line says `snapshot none`, the from side carries no `snapshot_id` key, and the document validates against the current contract with `step.schema.json`. `step.twin.unsteppable` is unchanged.

- [X] T043 [US5] `twin rehearse` (R-13). In `internal/server/rehearse.go`:
  - `rehearseStages` fills each `RehearseStage.SnapshotID`, the baseline's `ProvisionInput.SnapshotID` (`Source: intent`, as today) and each step's sides through `rehearsedStep`;
  - `rehearsalStages` and `report()` carry each row's id into `rehearsal.Stage.SnapshotID`;
  - a refused stage names null.

  Every stage's snapshot is taken in the plan, before the first boot, which the pipeline already guarantees, since the plan builds every stage up front. Tests in `internal/server/rehearse_test.go` and `internal/cli/twin_rehearse_test.go`:
  - a rehearsal whose third stage's read is refused is refused before the fake service starts any run, and the first two stages' snapshots are filed (US5 scenario 3);
  - the baseline's provision input and each step's sides carry the ids;
  - the rehearsal document validates against `rehearsal.schema.json`;
  - the markdown carries T021's column.

  - *2026-10-27, Run 11, the converge loop's session, at `00e81f1`:* **done.** `rehearseStages` sets each compiled stage's `RehearseStage.SnapshotID`, the baseline's `ProvisionInput.SnapshotID`, and both sides of each step through `rehearsedStep`. `report()` carries a compiled stage's id into `rehearsal.Stage.SnapshotID`, and a refused stage names none: even one whose compile was refused after its snapshot was filed, which `stage plan` names, as rehearsal.schema.json says (`null when the stage was refused`).
    - `internal/server`: the fixtures' compiled stages carry ids (`snapshotOf(label)`); `TestRehearseStagesAreTheStepChain` asserts them on the baseline, its provision and each step's sides; `TestRehearsalReportNamesEachStagesSnapshot` holds the block's ids (null for the branch point), validates the document, finds the seeded row's `| <snapshot8>… | <bundle8>… |` in the markdown, and holds a compile-refused stage's row to null.
    - `internal/cli`: `TestRehearseFilesEachStagesSnapshotBeforeAnyBoot` (US5 scenario 3): main carries the network, change-1 holds no device from third-link's at, so third-link and the head are refused `scope.empty` and the rehearsal is refused with no host read and nothing started (a read-only service), the branch point's and seeded's snapshots filed and named in the report. `TestRehearseEveryStagePasses` asserts the ids on the run's input and in the report; `TestRehearseMarkdown` finds each row's snapshot and bundle cells, `—` for the branch point.
    - Mutations, each caught: the take's id dropped in `build`; the from side's id; `StepDocument`'s id; the report's id; the baseline provision's id; the plan's `snapshot_id` line.

- [X] T044 [US5] Run `go test ./internal/stages ./internal/checks ./internal/rehearsal ./internal/server ./internal/cli` (tier 1) and fix what the ids broke in `internal/checks`' tier-1 tests. `internal/checks` reads the plan's and the rehearsal's documents and the report's markdown; any pinned header or row there moves to T021's. Read `infrahub/checks/fylgja_step.py` and `fylgja_twin.py`: neither parses a key that moved or the table's header (R-24). Note it in this task, and change nothing there.

  - *2026-10-27, Run 11, the converge loop's session, at `00e81f1`:* **done.** `go test ./internal/stages ./internal/checks ./internal/rehearsal ./internal/server ./internal/cli` is green. `internal/checks` has no tier-1 test (`[no test files]`), and its contract test pins no table header, row or id: nothing to move. `infrahub/checks/fylgja_step.py` reads `status`, `findings`, and each `plan.stages[]`'s `at_source` and `findings` (`rejections_past_branch_point` in `fylgja_api.py`); `fylgja_twin.py` reads `status`, `findings`, `rehearsal.stages` the same way and `rehearsal.deadline_s`, and posts `markdown` whole. Neither parses `snapshot_id`, `bundle_id` or the table's header (R-24). Nothing there changed.
    - The checkpoint: `make build` (static), `make test` exit 0 (48 s wall at load 3.8, then 42 s at load 4.35, Infrahub's `beam.smp` at 219 % CPU; `internal/cli` 37.3 s, about 35.5 s earlier in the session), `make lint` 0 issues, `go vet -tags contract,fixture,e2e ./...` clean, `git diff --stat main -- testdata/golden` empty. The code of the feature is complete in tier 1.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`. The
code of the feature is complete in tier 1.

---

## Phase 10: User Story 2, part 2 — the same intent, read twice, in Infrahub (Priority: P1)

**Goal**: tier 2 proves SC-002's first half: the same intent read twice, and the same
stage resolved twice through the server's path, give one snapshot id (R-16). The loop's
sessions hold Infrahub's address and token, so these two tests run in their run. No twin,
no worker and no server are needed.

**Independent Test**: `go test -count=1 -tags contract -run
'TestPinnedReadReproducesItsBundle' ./internal/stage` and `go test -count=1 -tags contract
-run 'TestStageTakenTwiceHasOneSnapshot' ./internal/server` both pass, and each leaves no
`fylgja-test-*` branch, proposed change or stage behind.

- [X] T045 [US2] Extend `TestPinnedReadReproducesItsBundle` in `internal/stage/reproducibility_contract_test.go` (tag `contract`). Wrap each read with `snapshot.Take`. The three reads pinned at T share one snapshot id beside the one bundle id the test already asserts, and the unpinned read after the change has another id. `t.Logf` both ids. Run it, with `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` from the environment and the token never printed, and record the result and its time in this task's note.

  - *2026-10-27, Run 12, the converge loop's session, at `6c143d6`:* **done.** The test's `read` takes each read with `snapshot.Take` and compiles the snapshot's CTM, as the server does, and returns the take. The CTM variable once named `snapshot` is now each take's `.CTM`, since the name now means the package. The two takes pinned to T after the first are held to its `snapshot_id`, beside the `bundle_id` checks already there. The unpinned take is held to another id. One assertion was added beyond the task: the first and last pinned takes stamped different `observed_at`s. Without it, one id could come from two takes that happened to stamp one time, and would not show that the id leaves `observed_at` out (R-01). The doc comment gains 018's paragraph. Run with `go test -count=1 -tags contract -run '^TestPinnedReadReproducesItsBundle$' -v ./internal/stage`, beside T046's, at load 2.0–3.6: **PASS** in 91.8 s (93.9 s wall). Branch `fylgja-test-repro-1793125741-7580`, T = `2026-10-27T18:29:38.052808Z`. Pinned at T before the change, after the regeneration and after the change: bundle `ea6632d3cb99714b33815c4c454f309d534c06f188caf6bb27b0ec04b6c32a70`, snapshot `a413827747e6c341e7032017df869f3887924fadb3705e7aba21386eb526a202`, all three. n1's checksum at T was `b16016d9…`, regenerated to `aed581e1…`. Unpinned after the change: bundle `b5fb3be3…`, snapshot `d01bac7da936a9fe23f8d9824b0e02b04221793b29b63c5c6b22a2934d914075`. The test's own cleanup deleted the branch.

- [X] T046 [US2] Add `TestStageTakenTwiceHasOneSnapshot` in a new `internal/server/snapshot_contract_test.go` (tag `contract`), composed as `rehearse_contract_test.go` is.
  1. A throwaway `fylgja-test-*` branch seeded through `testsupport`, a draft proposed change on it, and one stage marked.
  2. `runStagePlan` run twice through `testOptions` and `useStateRoot` on a temporary state root.
  3. Assert: every compiled stage's `snapshot_id` is equal across the two plans; the stored document's bytes and modification time are unchanged by the second plan; no `bundles/*.ctm.json` exists.
  4. At cleanup, delete the stages, then the proposed change, then the branch, as the existing contract tests do.

  `t.Logf` the id. Run it; record the result, its time and the id in this task's note. Afterwards read `CoreProposedChange` and `FylgjaStage` counts (0) and `Branch` (`main` and `fylgja-fixture` alone).

  - *2026-10-27, Run 12, the converge loop's session, at `6c143d6`:* **done.** The test is in the new `internal/server/snapshot_contract_test.go`. It reuses `rehearse_contract_test.go`'s `contractClient` and `seededBranch`, whose cleanup deletes the stages, then the proposed change, then the branch, and checks that none is left. So its branch is named `fylgja-test-rh-*`. It opens a draft and marks `seeded`. It runs `runStagePlan` twice through `testOptions` under `useStateRoot`, with `useService(t, nil)` guarding against a dial. Assertions:
    - Every stage names the same `snapshot_id` and `bundle_id` in both plans: equal strings, or null in both.
    - The mark and the head compile.
    - Each compiled stage's entry `Has` its id.
    - The store holds exactly the entries the first plan names.
    - Every entry is back-dated an hour after the first plan, as `TestPutKeepsTheFirstTake` does, and the second plan leaves each entry's bytes and back-dated modification time unchanged and adds none.
    - `bundles/*.ctm.json` matches nothing after either plan.

    Run with `go test -count=1 -tags contract -run '^TestStageTakenTwiceHasOneSnapshot$' -v ./internal/server`, beside T045's: **PASS** in 134.3 s (141.1 s wall). The seed took 46 s, the proposed change's pipeline 56 s, and the plans 9.7 s and 8.4 s, each exit 1. The branch point is refused `scope.empty`, since `main` holds no device, and names no snapshot in either plan. `seeded` is snapshot **`4345c3705678230162b4ee024af0a2794430db0156c19989af372d46b07bb659`** (bundle `b699cfea…`) in both. The head is snapshot `e8c31ea709a8ed0c6d368f31a998b2c0e6662bfcbfbe561359b747d253c246d1` (bundle `ae0cf7ee…`) in both. Cleanup: `deleted 1 stage(s), 1 proposed change(s), branch fylgja-test-rh-1793125804-1555`. Read afterwards at 18:32:33: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and `CoreUserValidator` each count 0. The creation ran both registered checks, which read through the operator's server (the 017 build, `(deleted)`) in its own state root; they write nothing to the branch, and both plans saw the same head.
    - The phase's checkpoint: `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` exit 0 in 42.3 s wall at load 3.56 → 3.12, with `internal/cli` 37.7 s, `internal/lab` 11.5 s and `internal/provision` 9.1 s. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `git diff --stat main -- testdata/golden` empty. Both tier-2 tests are green, and Infrahub is left as the contract tier leaves it. No tier-2 mutation was run, which would cost two more runs against Infrahub; T046's back-dating and T045's `observed_at` check keep each assertion from passing vacuously. `make build` rewrote `bin/fylgja`, so the worker (`3867740`) and the server (`3867762`) still read `(deleted)`. Neither was restarted: the worker is not this run's to stop, and the server waits for T050.

**Checkpoint**: `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`; both
tier-2 tests green; Infrahub left as the contract tier leaves it.

---

## Phase 11: User Story 6, part 2 — the end-to-end script and the contracts' prose (Priority: P3)

**Goal**: the end-to-end script asserts the snapshot where it asserted the sidecar, and
`cli.md` and `api.md` carry their 018 sections (FR-027, SC-006; R-17). The script is
written and checked here. It runs in Phase 12.

**Independent Test**: these checks run offline, never booting a twin: `shellcheck
scripts/e2e.sh`, and the changed `jq` filters against recorded outputs (`local/e2e-*.outputs`)
and against tier-1 documents.

- [X] T047 [US6] `scripts/e2e.sh` (R-17; snapshot-commands.md "Tier 3"). Make these changes:
  - `compiled_id` (lines 522–531) reads with `intent read --out "$OUT/snapshot-$case.json"` and compiles with `twin compile --snapshot`. Rename its files from `ctm-` to `snapshot-`.
  - `create_twin` (from line 560) reads `SID` from the create's `.snapshot_id` and asserts `snapshots/$SID.json` exists. Its line 595 sidecar check becomes "no `bundles/*.ctm.json` newer than the case's start": take a marker file at the case's start and use `find "$FYLGJA_STATE_ROOT/bundles" -maxdepth 1 -name '*.ctm.json' -newer "$marker"`, which must be empty. It expects `twin.json`'s `.snapshot_id==env.SID`.
  - Case 1's `twin show` grep (near line 871) gains `snapshot $SID1, bundle_id $BID1`.
  - Case 5's rebuilt twin expects `.show.record.snapshot_id==null`.
  - Case 7's steps expect `.step.to.snapshot_id` to be a string.
  - The destroy comment near line 1197 still names `.reads/` as the reconcile's.

  No case is added, and `PLATFORMS=nokia_srlinux` still ends `E2E-PARTIAL`. Run `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean. Check each changed `jq` filter offline against documents the tier-1 tests produce or against `local/e2e-*.outputs`, as the memory note on offline checks says: an old output must fail the new filter for the reason expected, and a hand-edited one must pass. Note the checks in this task.

  - *2026-10-27, Run 13, the converge loop's session, at `96c701a`:* **done; checked offline, not run.** `compiled_id` reads to `$OUT/snapshot-$case.json`, compiles it with `--snapshot`, and sets `COMPILED_SNAPSHOT` beside `COMPILED_ID`. `create_twin` touches `$OUT/began-<case>` before the create, reads and exports `SID` from `.snapshot_id`, expects `twin.json`'s `.snapshot_id==env.SID`, and asserts `snapshots/$SID.json`, the bundle's entry, and that `find "$FYLGJA_STATE_ROOT/bundles" -maxdepth 1 -name '*.ctm.json' -newer "$began"` is empty. Case 1's `twin show` grep holds `snapshot $SID1, bundle_id $BID1`. Case 5's rebuilt twin reads `.show.record | has("snapshot_id") and .snapshot_id==null`: the key is required, since a 015 document, which lacks it, passes a bare `==null`. Case 7's steps hold `.step.to.snapshot_id` a string, in each step's document and `twin.json`. The destroy comment names `bundles/.reads/` as the reconcile's alone. The header's case list says what moved. No case is added and no case's packages changed, so `PLATFORMS=nokia_srlinux` selects the same seven cases.
    - **Beyond the task's text**, each an id the run already holds:
      - **Marker grep:** its exclusion moves from `ctm-*.json` to `snapshot-*.json`. A read's snapshot carries the marker (3 lines in the fixture's), so the old exclusion would report a LEAK after every `compiled_id`.
      - **Cases 1, 2 and 4:** cases 1 and 2 hold the create's snapshot to the one `compiled_id` reads, as they hold the bundle. Case 4's create holds case 2's snapshot.
      - **Case 5:** the created twin's `twin show` names `SID5`. The rebuilt twin's text holds `snapshot none, bundle_id <id>`, SC-006's words.
      - **Case 7:** the plan names three distinct snapshot ids, the branch point's null. The create's snapshot is the plan's for `seeded`. Each step's from and to sides, and its document's `snapshot_id`, are the plan's for their stages. This is SC-002 and D-011 in tier 3: a stage's ids are one whichever command built it (Run 11, T040), and T046 found one snapshot for one stage taken twice.
    - **A scratch server from this build** ran the real commands. It listened on `127.0.0.1:0`, with its own state root in the session's scratch directory, a token made for it and no node logins. The operator's worker and server were untouched; it was stopped afterwards, and its log holds no token.
      - `compiled_id`, extracted verbatim and run against `fylgja-fixture`, read snapshot `576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482` and compiled bundle `f764e1fa…`, `CLAUDE.md`'s id. The store held `snapshots/576933ec….json`, and the summary line ends `; snapshot <id>, stored at <path>`. The old `--ctm` line is refused `unknown flag: --ctm`, exit 2.
      - A dry-run create was refused `host.probe.login_unset`, since that server holds no login. Its document still named the same snapshot and bundle at the top level, and no `*.ctm.json` was written.
      - `twin show` over hand-made records printed the record lines the greps read. A `9` naming the snapshot gives `record: branch fylgja-fixture, snapshot 576933ec…, bundle_id f764e1fa…, …`. A `9` naming none gives `snapshot none, bundle_id …`, and an `8` gives `snapshot none (record 8), bundle_id …`.
    - **27 `jq` filters**, extracted verbatim, were checked against the 015 run's `local/e2e-015-full-4.outputs` as recorded: each fails. The same documents, hand-edited to this build's shape but for the snapshot's keys, fail too. That shape is `twin_version` `9`, and for the plan, 017's `scope.empty` in place of 015's `contract.node.missing`. With the keys added, each passes. Five mutations each fail: a create naming none, two stages naming one snapshot, the refused branch point naming one, a step's to side naming none, and the record left at the from side's snapshot. The scratch server's own show documents pass case 5's null check when the record names none and fail it when it names one.
    - **15 shell checks**, each line taken verbatim:
      - Case 1's grep fails on 017's record line and on an `8`'s, and passes on this build's.
      - Case 5's text grep passes on a `9` naming none. It fails on a twin naming one, on 017's line and on an `8`'s.
      - The sidecar `find` over `local/bundles` is empty for a case started now. Back-dated to 10-26, it finds 84 sidecars and fails.
      - `snapshots/$SID.json` holds in the scratch store, but not in `local/`, which no 018 create has filed into.
      - The marker grep with the new exclusion finds nothing in the scratch outputs. With the old exclusion it finds the read's snapshot.
    - `shellcheck scripts/bring-up.sh scripts/e2e.sh` is clean. Tier 3 itself is T054's.

- [X] T048 [P] [US6] `contracts/cli.md` and `contracts/api.md`: append `## 018: snapshots` to each, after the 017 section. Use the text of [contracts/snapshot-commands.md](contracts/snapshot-commands.md)'s two sections, with relative links fixed for their new home: `snapshot.schema.json`, `formats.md`'s content, `../docs/decisions.md#d-061`. Fold `formats.md`'s per-schema changes into cli.md's "Formats and versions" table, as earlier sections do. In the earlier sections, mark `twin compile --ctm` and the sidecar retired, where they are described as current, with a one-line pointer to 018, as 017 marked what it retired. Run `make linkcheck` clean.

  - *2026-10-27, Run 13, the converge loop's session, at `96c701a`:* **done.** Both sections are appended after 017's. Their links are fixed: `../docs/decisions.md#d-061`, `api.md` and `cli.md`, and the schemas in place of `formats.md`.
    - **cli.md's section** is snapshot-commands.md's text, plus three things:
      - a bullet on the state root line `serve` and `worker run` print since T008;
      - a "Formats and versions" table that folds in formats.md's per-schema changes, one row each for the snapshot, `twin.json` `9`, findings (with `subject.snapshot` from T004), the `show`, `stages`, `step` and `rehearsal` blocks, the API, and the unmoved bundle manifest, CTM and PSP, followed by a bullet on the `017-dcim-reader/` frozen copies;
      - a Tier 3 paragraph that says what T047's script asserts.
    - **api.md's section** is the design's, plus the two `twin.compile` file refusals the server now words (`internal/server/compile.go`). Every quoted refusal and line was checked against the source, and the record lines against the scratch server of T047.
    - **The earlier sections** gain one-line pointers to 018, as 017 marked what it retired.
      - In cli.md: the title, the opening paragraph, `serve`'s state root line, the stage commands table (`intent read` writes a snapshot; `twin compile --ctm` is retired at 018 for `--snapshot <file>`), the file errors (`reading snapshot: …`, `writing snapshot: …`), the dry run's and the plan's filing (no sidecar), the M13 formats row, the workflows, tier 3, and 014's `stage plan` filing.
      - In api.md: the title, the opening paragraph, and the operations table, made current (`twin.create` `snapshot` with its file, `twin.compile` `snapshot`, `intent.read` the snapshot) with a "Moved at 018" sentence as 014's and 017's are. Also the `files` frame row, "Files"' `twin.compile` and `intent.read`, and 014's plan filing.
    - `make linkcheck`: 84 files, 1,880 relative links, 0 broken.

- [X] T049 [P] [US6] Check that the six moved schemas' and the new one's descriptions quote formats.md's 018 sentences exactly, and that `contracts/README.md` (if present) or the contracts index lists `snapshot.schema.json` with its version. Grep `contracts/` for `ctm.json`, `--ctm` and `sidecar`. Each hit is either historical, inside an earlier section, or made true.

  - *2026-10-27, Run 13, the converge loop's session, at `96c701a`:* **done; one description made true.**
    - **The quotes**, checked by script:
      - `twin.schema.json`'s description holds formats §2's quoted 018 sentence exactly.
      - Each property formats.md gives as JSON equals the schema's: `twin` `snapshot_id` (type and pattern), and the full specs of findings', `show.record`'s, `plan_stage`'s, the step side's and the rehearsal stage's `snapshot_id`, and `api.schema.json`'s `twin.create` `snapshot`.
      - The `required` lists match (the step side's alone lacks it), as do the enums (`source` in twin and show; `follow.reason` `snapshot`). `$id` is `…/twin/v9`, and `twin_version` is const `9`. `api.schema.json`'s request `files` description holds both of formats §8's strings.
      - `snapshot.schema.json` is byte-equal to the design's, and its description carries the bytes sentence and the `jq` recipe. The findings', show's, step's, rehearsal's and stages' descriptions each carry an 018 sentence; formats.md quotes none of those verbatim.
    - **The index:** there is no `contracts/README.md`. The index of formats with their versions is cli.md's "Formats and versions", and the 018 table lists `snapshot.schema.json` at `1`. `docs/development.md:367`'s repository listing names the schemas without versions, and lacks `snapshot` and 015's `rehearsal`. That is left for T057, whose file it is.
    - **The grep**, each hit classified:
      - `api.md` 120 and 225, and `cli.md` 18, 205, 211–217 and 396: pointed to 018 (T048).
      - `api.md` 223, inside "Files"' `twin.compile` bullet, now marked: historical.
      - `cli.md` 320 (014), and 879 and 915 (017), and `api.md` 387 (017): inside earlier sections.
      - The 018 sections: true.
      - **One made true:** `api.schema.json`'s answer `files` frame read `intent.read: one file, ctm.json, the CTM`. It now reads `intent.read: one file, snapshot.json, the snapshot (018; ctm.json, the CTM, before it)`, as `internal/server/read.go`'s `snapshotFile` names it. formats §8 did not name this description. No test pins it, and no frozen copy of `api.schema.json` exists.
      - `findings.schema.json` names `subject.ctm` with no description: T004's choice, kept for older documents.
    - **The phase's checkpoint:**
      - `make build` exit 0, `statically linked`.
      - `GOFLAGS=-count=1 make test` exit 0 in 40.6 s wall at load 1.43 → 3.13, with `internal/cli` 36.2 s, `internal/lab` 11.2 s and `internal/provision` 8.7 s.
      - `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean; `make linkcheck` 0 broken; `git diff --stat main -- testdata/golden` empty.
    - **Tier 2:** no task in this run names a tier-2 test, so none ran. Infrahub was only read: `fylgja-fixture`, by T047's scratch server. `Branch` lists `main` and `fylgja-fixture` alone.
    - **The processes:** `make build` rewrote `bin/fylgja`, so the worker (`3867740`) and the server (`3867762`) still read `(deleted)`. Neither was restarted: the worker is not this run's to stop, and the server waits for T050.

**Checkpoint**: `make test`, `make lint`, `shellcheck`, `make linkcheck`.

---

## Phase 12: User Story 6, part 3 — the host, live (Priority: P3)

**Goal**: the feature proved on the development host: the processes from this tree, the
hand checks of quickstart §2–§6, then the whole contract tier, then the end-to-end tier
whole and narrowed (SC-001–SC-006).

**Independent Test**: quickstart §2–§8's expected outcomes, each recorded in its task's
note.

- [X] T050 [live] Restart the worker and the server from this tree's `bin/fylgja` (`make build` first), as `CLAUDE.md` prescribes, and verify both:
  - `/proc/<pid>/exe` is not `(deleted)`;
  - the environments carry `INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT`, `FYLGJA_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`;
  - the server's report names `snapshots:` in its state root line (T008), both listeners, the plaintext warning, the default scope and both packages;
  - the worker's start-up report names `snapshots:`;
  - from inside each Infrahub task worker, `POST /v1/twin/show` answers `200` with the token and `401` without (`specs/015-proposed-change-rehearsal/quickstart.md` §2).

  Restart the dev server if it is down. Record the pids and lines, never a token.

  - *2026-10-27, Run 14, the converge loop's session, at `d71a7c4`:* **done.**
    - **The restart:** `make build` exit 0, `statically linked`. The worker (`3867740`) and the server (`3867762`), both `(deleted)` since Run 3, were stopped. Both were started again at 18:54:19Z by `CLAUDE.md`'s two lines: the worker is `342010` and the server `342070`. Each `exe` is `bin/fylgja`, not deleted. The dev server was up (`SERVING`), so it was not restarted.
    - **The environments:** both carry `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`, both logins, `FYLGJA_STATE_ROOT`, `FYLGJA_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`. Only the names were read.
    - **The server's report**, in order:
      - `listening on 127.0.0.1:7650 (API version 1, build 0.1.0-dev)`;
      - `listening on 172.17.0.1:7650 (…)`, then straight away `172.17.0.1:7650 is not a loopback address: the API's token is sent unencrypted on it`;
      - `state root …/local (bundles: …/local/bundles, snapshots: …/local/snapshots, twin: …/local/twin)`;
      - `default scope: tag:fylgja`;
      - both packages, each with `…_USERNAME set, …_PASSWORD set`.
    - **The worker's report:** the same state root line with `snapshots: …/local/snapshots`, both packages with their logins set, and `host: lab fylgja absent; twin directory absent`.
    - **The bridge:** from inside each of `fylgja-infrahub-task-worker-1` and `-2`, `POST /v1/twin/show` with the container's token answered `200 1 0.1.0-dev` (240 bytes read whole). Without the token it answered `401`, and so did the host without it.
    - **At the run's end:** the closing `make build` did not replace `bin/fylgja`, so both processes still read not deleted, and neither was restarted again.

- [X] T051 [live] [US1] [US3] [US4] The hand checks of quickstart §2 to §5, on a host with no twin (`twin show` → `none`), recording each outcome in this task's note:
  - **§2**: the wrapped fixtures compile to the goldens; `--ctm` is unknown, and the server's log shows no request; a hand-wrapped CTM compiles; `local/snapshots` count unchanged.
  - **§3**: two `intent read --out` of `fylgja-fixture` give one id, **the fixture's snapshot id for T062** (`576933ec…` is the candidate). Their diff is the two `observed_at` lines. The store holds the first take byte for byte. The `jq` recipe reproduces the id.
  - **§4**: the dry run's two `stored:` lines; the create `ok` with `f764e1fa…`. The run's activities read from `temporal workflow show` are `CheckHost, StageBundle, DeployLab, AwaitReadiness, PushConfig, RecordTwin, StopFollowing`, with no `ReadIntent` or `Compile` (SC-001). `twin show`'s record line; `twin.json` `9`; no sidecar newer than the create; a refused read (`--scope tag:nothing`) starting no run and filing nothing.
  - **§5**: the three refusals; the create from the id with no Infrahub request in the server's log; the kind `frozen; not following; built from snapshot …`; no `fylgja-follow` Schedule; `step.twin.unsteppable`; the file with no id; the file with a wrong id; a pinned read's snapshot showing `pinned at <T>; not following; built from snapshot …`.

  Destroy every twin at the end. Defects found get a tier-1 test pinning them, fixed in the package that holds the behaviour.

  - *2026-10-27, Run 14, the converge loop's session, at `d71a7c4`:* **done; no defect found, so no tier-1 test was added.** Six twins were created and each destroyed, and the host ends with no twin.
    - **§2, the hand tools:**
      - `twin compile --snapshot testdata/snapshot/three-node.json` gives `ok`, snapshot `6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6` and bundle `43d91715…`.
      - `mixed.json` gives snapshot `37d7378a…` and bundle `ecb665f5…`.
      - Each bundle written is `diff -r`-equal to its golden.
      - `--ctm` is `rejection operation.failed twin.compile: unknown flag: --ctm`, exit 2, and the server's log gains no line.
      - The hand-wrapped lossy CTM, and `testdata/snapshot/lossy.json`, are refused `platform.unsupported` for `c1` and `c2` (`no support package "chassisos"`), exit 1, because the server holds the shipped packages alone. This is Run 5's departure, now on the host. A second server from the same binary, on `127.0.0.1:7651` with `--psp-dir testdata/psp/lossy` and stopped afterwards, compiles both `ok` to `4213b3cf…` with the computed id `91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c`. That bundle equals the lossy golden.
      - `local/snapshots` was absent before and after: `twin compile` filed nothing.
    - **§3, the same intent read twice:**
      - Two `intent read --branch fylgja-fixture --out`, 6 s apart, give one id, `576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482`, the candidate. This is **the fixture's snapshot id for T062**.
      - Their `diff` is lines 4 and 9, the outer and inner `observed_at` (`18:55:42.651748Z` against `18:55:48.949360Z`), and nothing else.
      - `local/snapshots/576933ec….json` (6,769 bytes) is `cmp`-equal to the first take.
      - The summary line ends `; snapshot 576933ec…, stored at …/local/snapshots/576933ec….json`.
      - The `jq` recipe gives `576933ec…`. Each read took 1.2–1.3 s.
    - **§4, a create the server takes a snapshot for:**
      - Before it, `twin show` read `twin: none`.
      - The dry run prints `snapshot_id 576933ec…  stored: …/local/snapshots/576933ec….json`, then `bundle_id f764e1fa…  stored: …/local/bundles/f764e1fa…`, then `follow: would follow branch fylgja-fixture, checked every 5m0s` and `verdict: clear`.
      - `twin create --branch fylgja-fixture --no-follow --json` ended `ok` with `576933ec…` and `f764e1fa…` in 55.5 s.
      - Its run, `fylgja-provision 01a17eb8-5a0a-752d-9af7-121d6ab9d52b`, scheduled `CheckHost, StopFollowing, StageBundle, DeployLab, AwaitReadiness ×3, PushConfig ×3, RecordTwin`, and no `ReadIntent` or `Compile`. This is SC-001 on a real history.
      - `twin show`'s record line reads `record: branch fylgja-fixture, snapshot 576933ec…, bundle_id f764e1fa…, schema 7c413536d67ef86321c629c076a0d3a4, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9`, and the kind `frozen; not following`.
      - `twin.json` gives `"9"`, `576933ec…`, `intent` and a null `step`. Its `observed_at` is this create's own read (`18:56:11.804202Z`), not the stored take's, as R-11 has it.
      - No `*.ctm.json` in `local/bundles` is newer than the create; 481 older ones remain.
      - With the twin up, `twin create --branch fylgja-fixture --no-follow --scope tag:nothing` is `rejection scope.empty [step read]`, exit 1. No run started (the workflow count is unchanged), and `local/snapshots` stayed at 1.
    - **§5, a twin from a snapshot, frozen**, after `twin destroy`:
      - `--snapshot <id> --interval 1m` is `follow.flags.conflict [step start] --interval: --interval is meaningless with --snapshot: a twin built from a snapshot never follows`, exit 2.
      - `--branch` beside it is `snapshot.flags.conflict [step start] --branch: --branch is meaningless with --snapshot: a snapshot carries its own branch, at and scope`, exit 2. `--stage`, `--at` and `--scope` are refused the same way, each exit 2.
      - Each of those refusals is the server's guard: one `outcome=error` request line of 0–1 ms, before it dials Infrahub or the workflow service, as R-12 and the contract say.
      - The zero id is `snapshot.unknown [step resolve]`, exit 1, naming the id and the store `…/local/snapshots`.
      - **The create from `576933ec…` needs no Infrahub.** The server logs none of its requests to Infrahub, so its log cannot show this. Instead the create ran on a second server on `127.0.0.1:7651` whose `INFRAHUB_ADDRESS` was a closed port. There, a branch's dry run was refused `operation.failed` at `read` (`connection refused`), and the create from the id ended `ok` with `f764e1fa…` in 60.6 s.
      - On the operator's server, `twin show` gives the record line as in §4, `intent read at 2026-10-27T18:55:42.651748Z`, `(source snapshot)`, and `kind: frozen; not following; built from snapshot 576933ec…`.
      - `twin.json`: `source` `snapshot`, the id, `observed_at` the first take's, and a null `stage`.
      - `temporal schedule describe -s fylgja-follow` finds none.
      - `twin step --stage fylgja-fixture/head` is `step.twin.unsteppable [step resolve]`, "the twin was created from branch fylgja-fixture, not from a stage, …", exit 1.
      - The file with no id built a twin, `ok`, under `576933ec…`.
      - The file declaring `1111…` is `snapshot.id.mismatch [step resolve]`, "… declares snapshot_id 1111…, but its body hashes to 576933ec…; leave snapshot_id out to have it computed", exit 1, and no twin.
      - A read pinned at the first take's instant (`--at 2026-10-27T18:55:42.651748Z`) gives snapshot `01e9b883fadb2dacafe67e1676f19a9c789fe532543d0103363a49acc42343a5`, with the `at` in its envelope. The create from its id ended `ok` with bundle `d6479065…`. Its record reads `branch fylgja-fixture at 2026-10-27T18:55:42.651748Z, snapshot 01e9b883…`, its kind `pinned at 2026-10-27T18:55:42.651748Z; not following; built from snapshot 01e9b883…`, and no Schedule was made.
    - **Beyond the task's text:** a create from the second take's file (`observed_at` `18:55:48.949360Z`, its id declared) ended `ok`. Its `twin.json` records the stored first take's `observed_at`, `18:55:42.651748Z`, and the store's entry is `cmp`-unchanged. This is US3's scenario 8 and R-12, on the host.
    - **quickstart.md corrected** to what the host showed, as 017's Run 9 corrected its own:
      - §2: the lossy CTM needs a second server with its design-case package.
      - §3: the candidate markers are dropped for the values read.
      - §5: the no-request proof, since the server's log names no Infrahub request.

- [X] T052 [live] [US5] The hand checks of quickstart §6 on `B=fylgja-test-018`, recording each outcome in this task's note:
  - the throwaway branch, its proposed change and two stages, by the fixture tool;
  - `stage plan` twice, giving equal snapshot ids and the branch point `null`;
  - `twin create --stage $B/seeded`, then `twin step --stage $B/third-link --allow-restart`, whose document and `twin.json` name both sides' snapshots;
  - `twin destroy`;
  - `twin rehearse --branch $B --markdown`, whose header carries the `snapshot` column, within 4,092 bytes;
  - `-delete`.

  Afterwards `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange` and `FylgjaStage` count 0.

  - *2026-10-27, Run 14, the converge loop's session, at `d71a7c4`:* **done; one stage marked again, the quickstart's sequence corrected.** The fixture tool was built once with `-tags fixture` into the session's scratch directory and run from there.
    - **The branch:**
      - `-branch fylgja-test-018` seeded the three-node fixture with every artifact Ready.
      - `-propose` opened draft `18e2784e-7ca8-0e0e-33b7-c515e27088d4`; its 3 validators concluded in 47 s.
      - `-stage seeded` was marked at `19:05:34.211812`.
      - `-add-link` added `n1:ethernet-1/3 <-> n3:ethernet-1/3`, and `-stage third-link` was marked 2 s later.
    - **The first plan refused `third-link` `stage.artifact.stale`** for n1 and n3. Their intent was written at `19:05:34.878`, after their checksums' `19:04:25`. It refused the head the same way.
      - A plan 13 s later compiled the head, so the regeneration had landed in between.
      - The quickstart's sequence lacks the wait that `scripts/e2e.sh`'s case 7 makes (`await_checksums_moved n1 n3`): `-add-link`'s generate returns before the two are rewritten. The refusal is the guard working, not a defect.
      - n1's and n3's checksums had moved (`e6ef2e06…`, `e4ea36c0…`, all three Ready). So the stale stage was deleted on `main` (`FylgjaStageDelete`, stages being branch-agnostic) and marked again, at `19:06:58.756016`.
      - quickstart §6 now names the wait and the refusal without it.
    - **`stage plan --branch fylgja-test-018 --json`**, exit 1:
      - the branch point refused `scope.empty`, with `null` ids;
      - seeded: snapshot `f509731c38561f4bd44c88d21f2d6446f4b62cf47b4fedcce3771b29700a1fb0`, bundle `30d774a9…`;
      - third-link: snapshot `73acb037ee03bd14b1bc3a2514c98f6700822a3d673d478ec711257902613165`, bundle `ae199106…`;
      - head: snapshot `dd7be4364ee27b431a3b9161c989c8ff630b70cc9c32320441aec7b1cff238f5`, bundle `00fb18cb…`.
      - The text prints `  snapshot_id …` over `  bundle_id …` for each of the three.
      - The second plan's ids equal the first's (`same-ids-twice`). The store gained third-link's entry alone (4 → 5); the earlier plans had filed seeded's and the head's.
    - **The create and the step:**
      - `twin create --stage fylgja-test-018/seeded` ended `ok`, its record naming `f509731c…`.
      - `twin step --stage fylgja-test-018/third-link --allow-restart --json` ended `ok`, with `.snapshot_id` `73acb037…`, `.step.from.snapshot_id` `f509731c…` and `.step.to.snapshot_id` `73acb037…`.
      - `twin.json` (`"9"`) names the same three. `twin show`'s record line reads `…, snapshot 73acb037…, bundle_id ae199106…`.
      - Push n1 2.5 s, n3 2.9 s; settled after 5.0 s. Then `twin destroy`.
    - **`twin rehearse --branch fylgja-test-018 --markdown`**, exit 0, run `fylgja-rehearse 01a17ec4-e89f-79cb-b732-20a77233bbc5`:
      - It ended `rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 70.1s of the 1980s deadline`.
      - The report's header reads `| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |`. Each compiled stage's row names its snapshot (`f509731c…`, `73acb037…`, `dd7be436…`), and the branch point's reads `—`.
      - The report is 1,987 bytes, within 4,092.
    - **`-delete`:** `deleted 2 stages, 1 proposed change, branch fylgja-test-018`. Afterwards `Branch` lists `main` and `fylgja-fixture` alone. On `main`, `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread`, `CoreUserValidator` and `DcimPhysicalDevice` count 0.
    - **The run's checkpoint:**
      - `make build` exit 0, `statically linked`.
      - `GOFLAGS=-count=1 make test` exit 0 in 43.5 s wall at load 2.99 → 3.44, with `internal/cli` 36.0 s, `internal/lab` 11.6 s and `internal/provision` 9.3 s.
      - `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `git diff --stat main -- testdata/golden` empty.
    - **The host left clean:** `clab inspect --all` is `{}`, there is no `local/twin`, the Schedule list is empty, no workflow runs, and no `fylgja-test-*` branch remains. The worker and the server run from this tree. Tiers 2 and 3 are T053's and T054's, and neither ran.

- [X] T053 [live] The whole contract tier (quickstart §7). Preconditions: no twin on the host, and the worker and the server from this tree beside the bridge (T050). Run `set -a; . local/.env; set +a; make test-contract 2>&1 | tee local/018-contract.out`, started detached with its exit status in a file and waited on in foreground calls of under ten minutes. Expected green, about a minute over 017's 1,714.7 s. In the output: `TestPinnedReadReproducesItsBundle` and `TestStageTakenTwiceHasOneSnapshot` log their ids; `internal/stages` and `internal/checks` are green, `TestChecksInsideInfrahub` included, with the id in their rows (SC-006). Afterwards, Infrahub as the contract tier leaves it (`CLAUDE.md`, "Stages"). Record the total time, `internal/stages`' and `internal/checks`' times, and the ids. Never boot a twin while it runs.

  - *2026-10-27, Run 15, the converge loop's session, at `bd2dae2`:* **done; one defect in the tier's own tests, fixed in `1c0f97c`, and the failed package run again alone**, as Release 0.2's close ran `internal/stage` again.
    - **Before it:** `twin show` read `twin: none`. The worker (`342010`) and the server (`342070`) read `(deleted)` again. So `make build` (exit 0, `statically linked`) was run, and both were restarted at 19:17:32Z by `CLAUDE.md`'s two lines: the worker is `528336` and the server `528355`, neither deleted. Both environments carry the names T050 lists, and the reports read as T050's: `snapshots:` in both state root lines, both listeners, the plaintext warning, `default scope: tag:fylgja` and both packages with their logins set. From inside each task worker, `POST /v1/twin/show` answered `200 1 0.1.0-dev` (240 bytes read whole) with the token and `401` without. The dev server was `SERVING`. Infrahub held what `CLAUDE.md` says the contract tier leaves.
    - **The command:** `set -a; . local/.env; set +a; GOFLAGS=-v make test-contract > local/018-contract.out 2>&1`, started detached, its exit and times in files. `-v` was added because `go test` prints a passing test's `t.Logf` lines only with it, and the task asks for the ids. quickstart §7 now says so.
    - **The tier:** 1,814.4 s wall, 19:18:41Z → 19:48:56Z, at load 2.1 → 3.9. That is 99.7 s over 017's 1,714.7 s. Exit 2: every package green but `internal/cli`.
      - The longest packages: `internal/stages` 1,514.6 s (017: 1,422.1 s), `internal/server` 933.5 s, `internal/stage` 709.0 s and `internal/intent` 477.5 s.
      - `internal/checks`, the second `go test`, took 291.7 s (017: 278.8 s). `TestChecksInsideInfrahub` passed in 291.68 s against the server on `172.17.0.1:7650`, pid `528355`, which the test read as this tree's `bin/fylgja`.
    - **The defect:** `internal/cli` failed in 30.4 s, against 017's 207.7 s.
      - `TestSchemaCheckPassesOnBothFixtures` failed with `creating branch: Post "http://127.0.0.1:1/graphql/main": … connection refused`.
      - `TestSchemaCheckOnAMissingBranch` failed with its proxy's `HTTP 502` from the same address.
      - `TestSchemaCheckIssuesNoObjectQuery` passed without reaching Infrahub at all: its proxy records the path before forwarding it.
      - The cause is `85698fa` (T025's harness change). `TestMain` points `INFRAHUB_ADDRESS` at `http://127.0.0.1:1` and the token at a placeholder, so that no tier-1 test reaches the operator's Infrahub. `schema_contract_test.go` shares that binary under `-tags contract` and read the same variables.
      - The fix: the file keeps the shell's address and token as the package initialises, before `TestMain` runs, and `live` gives each contract test those values with `t.Setenv`. Tier 1 keeps its harmless defaults. No tier-1 test pins this, because the defect exists only under the contract tag, and that run is its test.
      - Run again alone with `go test -count=1 -timeout 30m -tags contract -v ./internal/cli`: `ok` in 66.9 s (77.1 s wall). `TestSchemaCheckPassesOnBothFixtures` passed in 29.93 s, seeding and deleting `fylgja-test-mixed-1793130607-9923`; `TestSchemaCheckOnAMissingBranch` in 0.01 s; and `TestSchemaCheckIssuesNoObjectQuery` in 1.19 s.
    - **`TestPinnedReadReproducesItsBundle`** passed in 205.17 s, on branch `fylgja-test-repro-1793129231-8885` with T = `2026-10-27T19:28:52.492917Z`.
      - The three reads pinned at T (before the change, after n1's regeneration and after the change) give bundle `4e9ccfb53b6a87404584a492c368e206ad3d0e130473241ffdcf93b6cc16c2f1` and snapshot **`201fa5e2efecb98c8dbd2886e91473ea13e9f464fd03fcea73345a4b3a48235e`**.
      - The unpinned read after the change gives bundle `7b164084…` and snapshot `2bab33dc92d5725c6c2617e1b7f6ea59a5f7cc167ac3e41b1c2446628cd91f55`.
    - **`TestStageTakenTwiceHasOneSnapshot`** passed in 178.96 s, on branch `fylgja-test-rh-1793129481-9774`: seed 30 s, the pipeline 92 s, the plans exit 1 in 10.1 s and 8.6 s.
      - `seeded`, taken twice: snapshot **`ffa1dac886d77dff5db6b4fde6f1848b020c5fda323530e8daa00842c7168754`**, bundle `d2755c9b…`.
      - The head: snapshot `98c33061ce0599a1803eb96ffce0d8ca0d73c4e14b8dcd4f9bcb72deb2075d23`, bundle `79772f1b…`.
      - The branch point is refused `scope.empty`.
      - Cleanup: `deleted 1 stage(s), 1 proposed change(s), branch …`.
    - **The id in the rows (SC-006):**
      - `internal/stages`' plan pipeline takes and files each stage's snapshot, and the package is green.
      - `internal/checks`' rows are rendered by the server on the bridge. Its store gained four entries under the test's branch `fylgja-test-ck-1793130286-2462` (`0406644f…`, `26fb2112…`, `ba4a670b…`, `7dd6d789…`), filed by the checks' `stage.plan` and `twin.rehearse` requests at 19:46–19:47.
      - The test asserts no snapshot itself (T021's note on formats.md §10). Tier 3's case 9 pins the header (T054).
    - **After it:** `Branch` lists `main` and `fylgja-fixture` alone. `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread`, `CoreUserValidator` and `DcimPhysicalDevice` count 0. `CoreReadOnlyRepository` holds `fylgja` alone with its two check definitions. No twin was booted while it ran.

- [X] T054 [live] The end-to-end tier, on a quiet host after T053, never beside it (quickstart §8). Preconditions:
  - `free -m` read;
  - the dev server, the worker and the server on the bridge from this tree;
  - Docker, containerlab, both images and Infrahub;
  - both checks imported on `main`.

  Run `make test-e2e` detached, its exit in `local/018-e2e.exit`, waited on in foreground calls under ten minutes. Expect `E2E-OK` in about 29.5 minutes. Rest the host, then run `PLATFORMS=nokia_srlinux make test-e2e`, ending `E2E-PARTIAL` in about 19. From the outputs, record:
  - every create's `snapshots/<id>.json`;
  - case 1's `twin show` text holding `snapshot <id>, bundle_id <id>`;
  - case 5's rebuilt twin with `.show.record.snapshot_id == null`;
  - case 7's steps naming the target's snapshot;
  - the credential greps clean;
  - both times.

  A failed attempt for the host's sake (a lost heartbeat, a starved deploy) is run again after a rest. A failure of the feature gets a tier-1 test and a fix before the re-run.

  - *2026-10-27, Run 15, the converge loop's session, at `bd2dae2`:* **done; one attempt lost to the host, the second green, then the narrowed run green.**
    - **Preconditions**, at 19:51Z:
      - `free -m` read 10,817 MiB available at load 2.3. Infrahub's containers held about 15 GiB, its server 7.9 GiB of that.
      - Both images present: `ghcr.io/nokia/srlinux:24.7.1` (`171ec8d41d6e`) and `ceos:4.32.0.2F` (`2b2efd540c12`).
      - The dev server `SERVING`.
      - `fylgja` registered at `cb0a8d7` with its two check definitions, and that commit in both task workers' `commits/`. 018 changes nothing under `infrahub/` or `.infrahub.yml` since it.
    - **The first start was refused at once:**
      - `make test-e2e` builds first. The uncommitted fix of T053 flipped `vcs.modified`, so the build replaced `bin/fylgja`.
      - Case 9's check then refused the server on the bridge, whose binary read `(deleted)`, before any case ran.
      - The fix was committed (`1c0f97c`) and `make build` run again (`vcs.modified=false`).
      - Both processes were restarted at 19:52:49Z (worker `612841`, server `612863`) and verified as T050's were: the environments, the reports, and from each task worker `200 1 0.1.0-dev` with the token and `401` without.
      - A second `make build` left the binary in place.
      - quickstart §8 now asks for a committed tree.
    - **Attempt 1** started 19:53Z (10,653 MiB available, load 2.1).
      - Cases 1–8 and 9a passed.
      - Case 9b failed. The `fylgja-twin` check concluded `failure` as expected, but at the baseline's deploy, not at `bad-port`'s push. SR Linux's `sr_cli` segfaulted in n3's containerlab post-deploy (`Segmentation fault (core dumped)`; the kernel logged `python[907983]: segfault … in python3.11` at 20:21:28), and containerlab cancelled n1's and n2's post-deploy.
      - The load was 5–6, with about 10.2 GiB available.
      - This is `docs/verified-facts.md`'s "under memory pressure SR Linux's own `sr_cli` can segfault", seen here on 26.04 for the first time, for T059.
      - The script's trap left no lab, no twin directory, no Schedule and no `fylgja-test-*` branch.
      - Its output is kept in `local/018-e2e-1.out` and `local/018-e2e-1.outputs/`.
      - A host failure, so the host was rested to a five-minute load of 2.4.
    - **Attempt 2** started 20:29:38Z (10,617 MiB available, load 1.1): **`E2E-OK`**, exit 0, wall 1,758.0 s (017: 1,769.0 s), boot half 9.0 s (case 1) and 8.0 s (case 6).
      - Creates: case 1 53.2 s, 2 44.7 s, 4 44.9 s, 5 45.2 s, 6 103.3 s, 7 54.3 s, 8 105.9 s.
      - Verify: 3.5 s (case 1), 3.9 s (case 5) and 3.0 s (case 6); case 8 settled after 4.472 s and 3.797 s.
      - Case 9's rehearsals: 69.9 s of the 1,980 s deadline (passed) and 76.2 s of the 2,610 s deadline (failed at `bad-port`'s push on n1, as designed).
      - Outputs are in `local/018-e2e.out` and `local/018-e2e.outputs/`.
      - **Every create's snapshot is filed** under `local/snapshots/<id>.json`:
        - case 1: `576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482`, bundle `f764e1fa…`, T051's fixture id;
        - cases 2 and 4: one snapshot, `839e80816e4ffbce2e2d66bb17651bc35d419b94205df4d3a3945b0b09936f58`, and one bundle, `0465c540…`;
        - case 5: `8af8d789…`, bundle `1f80f592…`;
        - case 6: `064bbfef…`, bundle `f271b7a8…`;
        - case 7: `1e097519…`, bundle `c6019f79…`;
        - case 8: `25023edb…`, bundle `78438299…`.
      - **Case 1's `twin show`** reads `record: branch fylgja-fixture, snapshot 576933ec…, bundle_id f764e1fa…, schema 7c413536d67ef86321c629c076a0d3a4, scope tag:fylgja, read by infrahub-dcim …`.
      - **Case 5's rebuilt twin** has `.show.record` holding `snapshot_id: null`, and its text reads `snapshot none, bundle_id 81d21e46…`.
      - **Case 7's steps:**
        - the plan gives seeded `1e097519…`, third-link `675bba24…` and the head `9719208f…`, and the create took seeded's;
        - step 7a ended `stepped`, from `1e097519…` to `675bba24…`;
        - step 7b ended `unchanged`, from `675bba24…` to `9719208f…`;
        - each document's top-level `snapshot_id` is its target's.
      - **Case 9:** both comments carry `| stage | at | snapshot | bundle | … |`, in 2,260 and 3,557 bytes.
      - **The credential greps:** `e2e: no credential and no marker in the run's outputs and the bundle store, the log of the server on the bridge …, and not the worker's log, since WORKER_LOG is unset`. Six values were also searched for: the Infrahub token, the API's token, the SR Linux password, the secret key, the agent token and the admin password. None was found in `local/worker.log`, `local/server.log`, this run's outputs and logs, or `local/snapshots`. Only counts were printed.
    - **The narrowed run** started 21:05:53Z, after a rest (10,591 MiB available, load 1.5): **`E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7 9; skipped 6 (…) 8 (…)`**, exit 0, wall 1,156.1 s (017: about 19 minutes).
      - Case 1's snapshot is `576933ec…` again.
      - Cases 2 and 4 share `02d759f6…`.
      - Case 5's rebuilt twin reads `null`.
      - Case 7 steps `b9079af3…` → `6032e920…` (`stepped`) → `9c1d2c65…` (`unchanged`).
      - The script's credential greps are clean.
      - Outputs are in `local/018-e2e-srlinux.out` and `local/018-e2e-srlinux.outputs/`.
    - **The host left clean:** `clab inspect --all` finds no containers, there is no `local/twin`, the Schedule list is empty and no workflow runs. `Branch` lists `main` and `fylgja-fixture` alone. `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread`, `CoreUserValidator` and `DcimPhysicalDevice` count 0. `main` holds the registration `fylgja` alone, the two check definitions, the queries `device_config` and `fylgja_branch`, and the group `fylgja-devices`. The worker (`612841`) and the server (`612863`) run from this tree.

**Checkpoint**: every tier green; the fixture's snapshot id known; the host left with no
twin and Infrahub as the contract tier leaves it.

---

## Phase 13: Polish — the records at the close

**Purpose**: every document says what is now true (FR-028, FR-029; R-18, R-23; quickstart §9).

- [X] T055 [P] `docs/architecture.md`, per R-18:
  - §2: the pipeline names the snapshot.
  - §3: a Snapshot row in the core objects' table.
  - §4.2: the CTM is the snapshot's body.
  - §4.3: the compiler's input is a snapshot's CTM.
  - §4.4: a create's provision begins at the host check; the sequence drawing; `ReadIntent` and `Compile` are the reconcile's alone.
  - §4.5: the state root tree gains `snapshots/` and loses the sidecar and its paragraph.
  - §4.6: the commands.

  Work through T002's grep hits and grep again (`ctm.json`, `sidecar`, `.reads`, `ReadIntent`, `--ctm`, `read and compile`). Every sentence is made true or marked historical. State the rebase and re-render limits once, linking D-061.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `docs/architecture.md`, through T002's hits and R-18's list:
    - §2: the pipeline paragraph and drawing name the snapshot (`snapshot 1`, `twin.json 9`, and `twin create --snapshot: no read` as an edge into it), and the stages' table gains a **Take** row; a step is "the same read, take and compile".
    - §3: the objects' drawing gains `──take──▶ snapshot`, the table a **Snapshot** row (the CTM's row now lives in "a snapshot's body", not the bundle store), and the rules "A snapshot is the core's one input", frozen by rule.
    - §4.2: the CTM is the snapshot's body; a new paragraph, **The snapshot**: version `1`, the id's hashed bytes, strict reading and its rules, the store that never overwrites, the hand wrap for a bare CTM, and that it crosses as a file alone. §4.3: the compiler's input is a snapshot's CTM, the wrapped fixtures compiling to the goldens; the secrets sentence names the snapshot in place of "the CTM file".
    - §4.4: the provision chain begins at `CheckHost`, every run started already compiled, `ReadIntent ─▶ Compile` kept for histories before 018; `ReadIntent` and `Compile` the reconcile's alone, `bundles/.reads/` named, no sidecar; a rebuild names no snapshot until F-026; the create's sequence drawing reads, takes and compiles on the server; the step and rehearsal chains say "taken"; following is a `--branch` create's.
    - §4.5: three directories, a snapshot store row, `snapshots/` in the tree with `.reads/` beside the bundles and the sidecar line gone, `twin.json` version 9 with `snapshot_id`, the sidecar paragraph replaced by its retirement, and a new **The record names its snapshot** paragraph.
    - §4.6: `twin create --snapshot`, `intent read --out snapshot.json` and `twin compile --snapshot` in the commands; the scope bullet, the server's components (`internal/snapshot`, and `stages`' arrow to it being the function the handlers hand it, not an import), the stage commands' files, `stage plan`, the step's dry run, `twin show`'s record and kind lines, the rehearsal's block and the API's "no fetch" all name the snapshot.
    - §6: one bullet states the rebase and re-render limits, linking D-061.
    - Grep again: `ReadIntent` hits are the reconcile's and the replayed histories'; `.reads` the reconcile's; `sidecar` and `--ctm` retirement notes. No "read and compile" left in a current sentence.

- [X] T056 [P] `docs/glossary.md`:
  - new entries: Snapshot, Snapshot id (with the hashed-bytes sentence and the two limits), and Snapshot store;
  - Bundle store without the sidecar;
  - Frozen twin and Pinned gain the snapshot twin;
  - Intent reference names the snapshot as a reference;
  - grep for `ctm.json`, `--ctm` and `sidecar`.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `docs/glossary.md`: new entries **Snapshot**, **Snapshot id** (the hashed bytes, the schema's `jq` recipe, the two limits, the fixture's `576933ec…`) and **Snapshot store**. **Bundle store** loses `PutCTM` and the sidecar, with its retirement and `.reads/` named. **Frozen twin**, **Pinned** and **Kind** gain the snapshot twin; **Intent reference** names the snapshot as a reference with `snapshot.flags.conflict`. Also moved: **Client** (`--snapshot` among its files), **Compiler**, **CTM**, **Dry run**, **Interval**, **`observed_at`**, **`provision` (workflow)** (already compiled), **Rebuild** (names no snapshot), **Stage commands**, **Stage reference**, **State root**, and **`twin.json`** (`9`, `snapshot_id`, `source`, an `8` naming none). Grep: `ctm.json`, `--ctm` and `sidecar` hit retirement notes alone.

- [X] T057 [P] `docs/development.md`: the state root listing gains `snapshots/`, and the frozen copies' paragraph names `017-dcim-reader/`'s sixteen copies and the count `49`. Note the snapshot's tier-1 tests where the tiers are described. Grep for `--ctm` and `ctm.json`.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `docs/development.md`: the layout gains `internal/snapshot/` and `testdata/snapshot/`, and `local/`'s state root lists `snapshots/` (`.reads/` worded as the check's); the frozen copies' paragraph names the sixteen under `017-dcim-reader/` and the count 49 (counted: 49 files, `TestFrozenContractCopiesAgree` green); tier 1's cell gains **The snapshot** and the API's snapshot cases; tier 2's cell names the snapshot ids in `TestPinnedReadReproducesItsBundle` and `TestStageTakenTwiceHasOneSnapshot`, and T053's times (1,814.4 s; `internal/stages` 1,514.6 s, `internal/server` 933.5 s, `internal/stage` 709.0 s, `internal/intent` 477.5 s, `internal/checks` 291.7 s, `internal/cli` 66.9 s alone); tier 3's assertions and T054's times (1,758.0 s, narrowed 1,156.1 s); the constants table gains the snapshot store. Grep: no `--ctm` or `ctm.json`; `.ctm.json` appears only in the tier-3 sentence on the retired sidecars.

- [X] T058 [P] `README.md`:
  - the offline walk-through compiles `testdata/snapshot/mixed.json` with `twin compile --snapshot` to `ecb665f5…` (R-15);
  - the `intent read --out` lines say a snapshot;
  - the stage commands' sample lines gain `snapshot_id`;
  - the rehearsal table sample (line 569) gains the `snapshot` column.

  Run every command shown that needs only the server against this tree, and paste its real output.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `README.md`: the offline walk-through runs `twin compile --snapshot testdata/snapshot/mixed.json`, run here against the server from this tree (pid `1494776`): `ok`, snapshot `37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf`, bundle `ecb665f5…`, the two `artifact.interface.unrepresented` warnings, exit 0, and the same three links; pasted with the path the README uses. `local/snapshots` held 67 entries before and after: the compile filed nothing. "The stages on their own" says `intent read --out snapshot.json`, `twin compile --snapshot` and the hand wrap, `--ctm` retired. The stage plan's sample, `fylgja-step`'s message and the step's twin line gain `snapshot_id` and `snapshot`; the rehearsal table gains the `snapshot` column; the create's sample shows its two `stored:` lines in place of the run's read and compile, and the record lines name the snapshot (a rebuild's `snapshot none`); "Pinned and frozen twins" gains `twin create --snapshot`. Every other sample needs Infrahub or a twin, so it was not re-run: the README's samples were recorded at `v0.2.0`, and its note now says the lines 018 changed are shown as this build prints them, with the snapshot ids, which that release did not take, trimmed to `…`, as 017's lines were.

- [X] T059 [P] `docs/verified-facts.md`: under 2026-10-27, research §1.2 (two unpinned reads differ in `observed_at` alone) and §1.3 (the hashed-bytes encoding and the `jq` recipe agree), with T051's fixture id and T046's stage-taken-twice result, each with Infrahub 1.11.2 and the date.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `docs/verified-facts.md`, Infrahub 1.11.2, "Reading intent": two unpinned reads differ in `observed_at` alone (§1.2), with T051's fixture id `576933ec…`; a stage resolved twice has one snapshot (T046's `4345c370…`/`e8c31ea7…` and T053's `ffa1dac8…`/`98c33061…`, and T045's pinned reads); and the `jq` recipe (§1.3), re-run here with jq 1.8.1: the schema's recipe over the stored fixture snapshot gives `576933ec…` and over the three wrapped fixtures their ids, and the bare-CTM recipe over `testdata/ctm/` the same three. Beside them, two host facts the runs found: the `sr_cli` segfault on 26.04 under load (T054's first attempt), and go1.26.8 in place of go1.26.0 (T001).

- [X] T060 [P] `docs/roadmap.md`: F-024 marked built by 018, with a one-line summary and links to D-061 and this feature; Release 0.3's list moves its marker to F-026 next. The brief (`specs/018-snapshots/brief.md`) is left as written.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `docs/roadmap.md`: Release 0.3's item 2 marks F-024 **built** on 2026-10-27 under D-061 and Constitution 2.2.0, and item 3, F-026, is **the next spec**; the backlog's paragraph names F-011 and F-024 built; F-024's row and its paragraph say built as `018-snapshots`, with one summary sentence; "Decisions the order needs" says it was taken as D-061 with 2.2.0. The brief is left as written.

- [X] T061 [P] Re-read `SECURITY.md` and `.env.example` for anything the snapshot changes. Expected: nothing in `.env.example`. A sentence in `SECURITY.md` that a snapshot holds configuration, as the CTM does, if it describes the CTM's or the bundle store's contents. Grep the tree for any log or finding message that could carry a snapshot's bytes (`grep -rn 'snapshot' internal/server/*.go | grep -i 'log\|Printf'`). Only ids and paths may cross.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `SECURITY.md` describes no CTM's or store's contents, so no configuration sentence is added; its credential lists gain "a snapshot", which T054's greps over `local/snapshots` hold true. `.env.example`: its no-value sentence names the snapshot, and the state root's comment `snapshots/`. The grep `grep -rn 'snapshot' internal/server/*.go | grep -i 'log\|Printf'` finds the read's summary clause, the record line, the stored lines and the refusals: ids and paths alone. The `internal/snapshot` messages carry a version, a field name, a count, ids and paths, never the document.

- [X] T062 `CLAUDE.md`:
  - Formats: snapshot `1`; `twin.json` `9`; `--ctm` retired; the fixture's snapshot id from T051 beside `f764e1fa…`.
  - The Environment's description of the server's report: `snapshots:` in the state root line.
  - Build and test: tier 2's and tier 3's new times from T053 and T054, and the tier-1 time if it moved.
  - The fixture branch's paragraph: "It compiles to `f764e1fa…` … and its snapshot id is `<id>`".
  - State: 018 closed, summarised as 017's entry is (D-061, Constitution 2.2.0, the snapshot store, `twin.json` `9`, the sidecar retired, the tiers' results); **Next**: F-026.
  - The constitution's version where `CLAUDE.md` names it (2.2.0).

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.** `CLAUDE.md`: the constitution named 2.2.0; Formats gain snapshot `1`, `twin.json` `9`, `snapshot` on the API, `--ctm` and the sidecar retired, the wrapped fixtures, and the live fixture's snapshot `576933ec…`; the fixture branch's paragraph names its snapshot id in full; the server's report names `bundles:`, `snapshots:` and `twin:`; Go is go1.26.8; Build and test carry tier 1's 40.6 s (T063), tier 2's 1,814.4 s with `internal/stages` 1,514.6 s and `internal/checks` 291.7 s, and tier 3's 1,758.0 s and 1,156.1 s; State: Release 0.3's five specs, **018** closed, **Next** F-026, and 018's command log and review among the operator's open items.

- [X] T063 The closing gates and greps:
  - `make build`, static; `make test` uncached under 45 s; `make lint`; `go vet -tags contract,fixture,e2e ./...`; `shellcheck scripts/bring-up.sh scripts/e2e.sh`; `make linkcheck`;
  - `git diff --stat main -- testdata/golden` empty;
  - `/usr/bin/grep -rn -- '--ctm\|PutCTM\|\.ctm\.json\|sidecar' --include=*.go --include=*.md --include=*.sh --include=*.json --include=*.dsl .`, excluding `specs/0[01]*`, `local/` and `.venv/`. Each hit is historical, the reconcile's `.reads/`, or a retirement note;
  - the credential greps over the tree and the branch's history (`/usr/bin/grep`, since Bash's `grep` skips git-ignored files), finding nothing;
  - `TestFrozenContractCopiesAgree` at 49.

  Record each result in this task's note.

  - *2026-10-27, Run 16, the converge loop's session, at `c5e104c`:* **done.**
    - `make build` exit 0, `statically linked`. `GOFLAGS=-count=1 make test` exit 0 in 40.6 s wall at load 1.45 → 2.57, `internal/cli` 36.2 s, `internal/lab` 11.5 s, `internal/provision` 9.2 s. `make lint` `0 issues`; `go vet -tags contract,fixture,e2e ./...` clean; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean; `make linkcheck` `84 files, 1911 relative links checked, 42 external skipped, 0 broken` (and clean again after the brief's edit below).
    - `git diff --stat main -- testdata/golden` empty.
    - The retired names: the task's command passes `--include` after `--`, so grep reads them as files; run as `/usr/bin/grep -rn --include=… -e '--ctm\|PutCTM\|\.ctm\.json\|sidecar' .`, 105 hits outside `specs/0[01]*`, `local/` and `.venv/`. Each is a retirement note (contracts' 018 sections and pointers, D-061, the records above, code comments), the reconcile's `.reads/` (`internal/provision`, its tests), an earlier decision's history (D-038, `docs/decisions.md:2227`), a test asserting no sidecar, or a test's own temporary `*.ctm.json` file. One was none of these: `docs/brief.md` still listed `twin compile --ctm` and `--out ctm.json` and drew the pipeline without the snapshot, so its CLI and drawing were made true and the principles gained the snapshot.
    - The credential greps (`/usr/bin/grep -F`, counts and file names only): the Infrahub token, the API's token, the secret key, the agent token and the admin password are in no file of the tree (`.git`, `local/`, `.venv/` and `bin/` aside), in none of the 52 commits' diffs on `main..HEAD`, and in no commit message. The node logins are the images' published defaults: the SR Linux one is in `scripts/bring-up.sh`, `scripts/e2e.sh` and two tests as before, and in no line of the branch's diffs; the EOS one is a five-letter lowercase word that appears throughout the tree as prose, and its nine lines in the branch's diffs are that word in prose.
    - `TestFrozenContractCopiesAgree` passes, with 49 copies under `internal/*/testdata/contracts/`.
    - `make build` rewrote `bin/fylgja`, so the worker (`1494754`) and the server (`1494776`) read `(deleted)`; neither was restarted (this run may not stop the worker, and nothing here needs the server again).

- [ ] T064 [operator] The operator's review of the feature, the commits by hand that the runs left uncommitted, and `make command-log` once the session is closed. Record the review's outcome in this task's note.

  - *2026-10-27 21:58Z, at `3518b4e`, Run 17 of the converge loop (live): left unchecked.* The review is the operator's, and a session cannot run the command log for a session that is still open. Nothing was merged, pushed or fetched. What is ready:
    - **The feature's diff**: `git diff 168fd63 3518b4e`, from `main` as it stood before 018's specify. It is 56 commits (19 `feat`, 1 `refactor`, 11 `test`, 25 `docs`) over 177 files, +19,998 and −1,373 lines. The code is 37 Go files (+1,733 −367) and their tests 77 (+5,726 −629). The 16 contract copies frozen under `internal/*/testdata/contracts/017-dcim-reader/` add 6,793 lines, and the feature's 11 files under `specs/018-snapshots/` 3,968.
    - **`origin`**: its `main` is `cb0a8d7`, read with `git ls-remote` at 21:57Z, which moves no remote-tracking ref; it is an ancestor of the branch, and local `main` (`168fd63`) is one `docs` commit past it. No CI run has seen 018's code. 018 changes nothing under `infrahub/`, `.infrahub.yml`, `schema/` or `testdata/golden/`, so no import into Infrahub is owed and no task here waits on a push, as 017's T057 did. The merge and the push are the operator's, once the review is done; CI's contract job runs on that push.
    - **To read on their own**:
      - D-061 (`9378915`), with Constitution 2.2.0 (`4fc1635`).
      - The four breaking commits: `d110840` (`twin.json` 9), `e4c0a62` (the CTM sidecar retired), and `82b05cc` with `4874612` (`twin compile --snapshot` in place of `--ctm`).
      - The contract `c07214f` (`snapshot.schema.json`, version 1), and the frozen copies, landed in `c3009ed`, `82b05cc`, `d110840` and `ed39b9b`.
      - No golden re-baseline: `6bb34f9` proves the three wrapped fixtures compile to `43d91715…`, `4213b3cf…` and `ecb665f5…`, unmoved.
    - **What a session decided where the documents left it open**, each in its task's note:
      - Run 5 (T015): the lossy fixture compiles through `testdata/psp/lossy`, the registry its golden was compiled with.
      - Run 7: the five contracts frozen as this file's header decides (T020); no file in `internal/checks` pins the report's header, though formats.md §10 and R-14 say one does, so case 9 of `scripts/e2e.sh` moved instead (T021); `rehearsal.steps.none` still judges by count, not bundle equality, since "still raises it" could not hold (T021).
      - Runs 8–10: the take's and the store's refusals at `compile`, not `read` (T025, T040); a snapshot create's subject names the envelope's `branch` and `at` and no scope (T030); the packages load before the snapshot resolves (T031); the client's own id check, held to `snapshot.IsID` (T033); a frozen snapshot twin keeps the frozen rule's best-effort note (T034); M1's documents held to the current contract (T037); the state root resolved before an `intent read` (T038); `PlanStage.SnapshotID` a field, not a method (T040).
      - Run 16: the README's samples kept from the v0.2.0 recording, with the ids that release never had written `…` (T058); a line each in `SECURITY.md` and `.env.example`; the architecture's sentence on the server diagram's arrows reworded, the diagram unchanged; T063's grep run with `-e`.
      - And, for `analyze`, R-21 (Notes): `twin verify`'s block names no snapshot.
    - **The host, beyond the feature**: with no twin up, `free -m` reads 10,473 MiB available, not the about 24 GiB `CLAUDE.md` gives. Infrahub's eight containers hold about 15.4 GiB, its server 7.97 GiB, after 14 days up, against the 5.2 GiB idle `CLAUDE.md` records. Run 15 (T054) lost one tier-3 attempt to an SR Linux `sr_cli` segfault under that load. Restarting Infrahub's containers, or changing the figure, is the operator's call.
    - **Commits by hand**: none are owed. Each run committed its own work, and the tree was clean at `3518b4e` before this note.
    - **The command log**: `local/command-log/` holds no `pending.jsonl`. The loop publishes each session's entry when the session exits: 20 are in `specs/018-snapshots/commands/runs.jsonl` (`specify`, `clarify`, `plan`, `tasks`, `analyze`, and Runs 1 and 3–16), and this session's follows when it exits. `make command-log`, run after the attended session closes, publishes whatever that session kept.
  - *2026-10-27 22:10Z, the operator's answer to the attended loop's question 1: "1a".* T064 is left for the operator at the feature's close: the review covers the whole branch once the loop has stopped, with any commits a later convergence pass adds, and the outcome is recorded here then. The operator stopped the loop and had Infrahub's containers restarted to win back the memory the host note above describes.

**Checkpoint**: every record true; the feature closed.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: T001 first. T002–T005 are the operator's. T002 blocks T009 onward.
  T003 blocks T016 onward. T004's answers may change T020, T025, T030 and T047. T005 any
  time after T001.
- **Foundational (Phase 2)**: after T001 and T002. T006, T007 and T008 in parallel, before every
  task that files a new rule, validates a snapshot, or names `paths.Snapshots`.
- **US2 part 1 (Phase 3)**: after T002 and Phase 2. T009 → T010 → T011; T012 and T013
  after T011, in parallel.
- **US4 part 1 (Phase 4)**: after Phase 3. T014 → T015.
- **US6 part 1, the records (Phase 5)**: after T003 and Phase 3. T016 → T017 → T018;
  T019 beside T016; T020 after T019; T021 after T019; T022 after T016 and T020.
- **US1, the MVP (Phase 6)**: after Phase 5. T023 → T024 → T025 → T026 → T027; T028
  after T025; T029 after T024, in the same commit as the component it draws or the next.
- **US3 (Phase 7)**: after Phase 6. T030 → T031 → T032 → T033; T034 after T022; T035
  last.
- **US4 part 2 (Phase 8)**: after T024 and T031 (the error mapping). T036 → T037; T038 →
  T039. The two pairs touch different files and may run side by side.
- **US5 (Phase 9)**: after Phase 6 and T021. T040 → T041; T042 and T043 after T040; T044
  last.
- **US2 part 2, tier 2 (Phase 10)**: after Phase 9. T045 and T046 in parallel.
- **US6 part 2 (Phase 11)**: T047 after Phases 6–9. T048 and T049 after Phase 9.
- **The host, live (Phase 12)**: after Phase 11. T050 → T051 → T052 → T053 → T054. T053
  never beside a twin, and T054 never beside T053.
- **Polish (Phase 13)**: after Phase 12. T059 needs T046's and T051's results; T062 needs
  T051's id and T053–T054's times. T055–T061 together; T063 after them; T064 last.

### Within a phase

Pure code is gated in tier 1 before its harness, tier-2 or live proof. A story's test names
the scenario it proves. A defect a test finds is fixed in that phase, in the package that
holds the behaviour, before the checkpoint. A live task's defect gets a tier-1 test that
pins it.

### Parallel opportunities

- Phase 2: T006, T007 and T008.
- Phase 3: T012 and T013, once T011 is in.
- Phase 5: T019 beside T016–T018.
- Phase 8: T036–T037 beside T038–T039.
- Phase 9: T042 beside T043, once T040 is in.
- Phase 10: T045 beside T046.
- Phase 11: T048 and T049 beside T047.
- Phase 13: T055–T061 together.

### Parallel example: the foundation

```text
T006  internal/findings/finding.go, finding_test.go, render.go   (the identifiers)
T007  contracts/snapshot.schema.json                             (the contract)
T008  internal/lab/env.go, cmd/fylgja/serve.go, worker.go        (the path)
→ then T009–T011 in order, then T012 beside T013
```

### Parallel example: User Story 5

```text
T040        internal/stages/plan.go, blocks.go                   (the pipeline's Take)
→ T042      internal/server/step.go, internal/cli/twin_step_test.go
  T043      internal/server/rehearse.go, internal/cli/twin_rehearse_test.go
→ T044      internal/checks/
```

---

## Implementation Strategy

**MVP**: Phases 1–6. After Phase 6, every create the server starts is read, taken,
compiled and filed on the server, and the provision workflow begins at the host check. The
record names the snapshot and no build writes a sidecar, proved in tier 1. Phase 12 proves
it on the host.

**Incremental delivery**: the identifiers, the contract and the path → the snapshot, its
id and its store → the wrapped fixtures → the records and the wire → the create (MVP) →
`--snapshot` on create → the hand tools → stages, step and rehearsal → the two tier-2
tests → the end-to-end script and the contracts' prose → the host, live → the records.
Every checkpoint leaves the tree green, and no golden moves.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

1. **Run 1** — the baseline: the pure gates and the tree's state read (T001). Only this; stop and report.
2. **Run 2** — [operator] D-061 accepted and appended, Constitution 2.2.0 and the plan template, the plan's six departures and this file's four decisions settled, the roadmap's edits and the design committed (T002–T005). Stop and report.
3. **Run 3** — the five identifiers, the snapshot's contract landed, and paths.Snapshots in the state root lines (T006–T008). Only these; stop and report.
4. **Run 4** — internal/snapshot: the document, Take, the hashed bytes and the id with the reflection test, Unmarshal's refusals in order, the store, the id's and the store's tests over the fixtures and the contract, and the C4 model redrawn with the package and the store (T009–T013). Only these; stop and report.
5. **Run 5** — the three wrapped fixtures under testdata/snapshot and their compile to the three goldens, no golden moved (T014–T015). Only these; stop and report.
6. **Run 6** — twin.json 9 with the 8 frozen, the workflow inputs with the nine histories replaying, the step and rehearse workflows carrying the sides' ids (T016–T018). Only these; stop and report.
7. **Run 7** — the findings blocks, the five moved contracts with their sixteen frozen copies, the rehearsal's snapshot column, and twin show's record line (T019–T022). Only these; stop and report.
8. **Run 8** — the sidecar retired, takeSnapshot, the create read, taken, compiled and filed on the server with its dry run, the create's tests, the follow's rebuild naming none, and the C4 model redrawn (T023–T029). Only these; stop and report.
9. **Run 9** — twin create --snapshot: the guards, resolveSnapshot by id or file, the API's argument and file, the client's flag, twin show's kind for a snapshot twin, and the tests (T030–T035). Only these; stop and report.
10. **Run 10** — twin compile --snapshot with --ctm retired, and intent read --out writing and filing a snapshot, with their tests (T036–T039). Only these; stop and report.
11. **Run 11** — the stages' pipeline takes each stage's snapshot; stage plan, twin step and twin rehearse carry it; the checks' tier-1 tests (T040–T044). Only these; stop and report.
12. **Run 12** — the two tier-2 tests written and run: the pinned read's snapshot id, and one stage taken twice through the server's path (T045–T046). Only these; stop and report.
13. **Run 13** — the end-to-end script's assertions moved to the snapshot and checked offline, and the contracts' 018 sections (T047–T049). Only these; stop and report.
14. **Run 14** — [live] the worker and the server restarted from this tree and verified, and the hand scenarios of quickstart §2–§6 (T050–T052). Stop and report.
15. **Run 15** — [live] the contract tier whole beside the server on the bridge, then tier 3 whole and narrowed on a quiet host (T053–T054). Stop and report.
16. **Run 16** — the records: architecture, glossary, development.md, README, verified-facts.md, roadmap, SECURITY.md and .env.example re-read, CLAUDE.md, then the closing gates and greps (T055–T063). Only these; stop and report.
17. **Run 17** — [operator] the operator's review, commits and the command log (T064). Stop and report.

`converge` follows Run 17.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route"
only up to the next heading.

**For `analyze` to settle**, beside T004's list:

- **R-21, `twin verify`**: its block keeps `verify.twin.bundle_id` alone, against a
  literal reading of SC-005 ("every record that names a bundle id names a snapshot id or
  says it has none"). FR-022's list of five records is what this file builds. Verify's
  block is a document, not a record, and moves at F-026.
- **SC-001's proof**: tier 1 shows it on the workflow's input shape (T017), and T051 shows
  it on a real history. Tier 3 adds no assertion for it, since no case is added (SC-006).
- **The rebase and re-render limits** are stated in the schema (T007), the glossary
  (T056), the architecture (T055) and D-061 (T002), and tested by nothing, as the spec's
  Assumptions say.

---

## Phase 14: Convergence

- [X] T065 [pin] Bring `twin create`'s help to 018, with no code path changed. `internal/cli/create.go` (lines 50–52) still says what the provision workflow did before 018: Short "Read, compile and provision one twin from a branch", Long "Read an Infrahub branch, compile it and provision the twin through the lab host's worker, as one run with the fixed identity fylgja-provision". Since 018 the API's server reads, takes the snapshot, compiles and files the bundle before any run, and the run begins at the host check (FR-009); `--snapshot <id|file>` builds a twin from a snapshot with no read of any branch, frozen (FR-015, FR-016). The `--dry-run` flag's help (line 78), "read, compile, file the bundle and check the host; start no run", leaves out the snapshot it files and that a `--snapshot` dry run reads nothing. Word the server's part as `twin step`'s and `twin rehearse`'s long help word theirs ("The API's server resolves, reads, compiles and files …"), naming the snapshot and `--snapshot`, and keep the run's part (from the host check, `fylgja-provision`, the interrupt). No test pins these strings (`grep -rn "Read an Infrahub branch, compile" internal/cli` finds none); pin in `internal/cli` that `twin create --help` names `--snapshot` and the server's read, take and compile, as `TestCompileTakesNoCTM` pins `twin compile`'s help (US4/AC4). per FR-009, FR-015 (partial)
  - *2026-10-27, Run 18 of the converge loop:* done, at `1a29956`. `twin create`'s Short is "Provision one twin from a branch, a stage or a snapshot", and its Long says the API's server resolves the stage, reads the branch, takes the snapshot of what it read, compiles it and files the snapshot and the bundle, before any run; that `--snapshot <id|file>`, a stored id or a file sent, which the server files, reads no branch and never follows; and that one run with the fixed identity `fylgja-provision`, from the host check on, provisions the twin, with the readiness wait and the interrupt's words kept. "Never follows" rather than "frozen": FR-017 calls a snapshot twin pinned when its envelope has an `at`. `--dry-run`'s help is "read, take and file the snapshot, compile and file the bundle, and check the host; start no run (with --snapshot, nothing is read)", as `runCreateFromSnapshot`'s dry run does. `TestCreateHelpNamesTheServersTake` (`internal/cli/create_from_snapshot_test.go`) pins seven phrases of the help, its whitespace folded so no line break is pinned, and that the old "Read an Infrahub branch, compile it" is gone. No doc quoted the old strings (`/usr/bin/grep` over the tree finds them only in this task).

- [X] T066 [pin] Bring `docs/development.md`'s tier-3 case list to `scripts/e2e.sh`, with no code changed. Case 7 (line 702) says the create's "`twin.json` `8` names the stage and the proposed change"; the script holds it to `9` (`TestE2EScriptExpectsTheRecordsVersion`, T016), and its header says `twin.json 9`. The paragraph before the cases (lines 663–667) names every create's snapshot assertions, but no case names those T047 added, which the script's header (lines 22–54) and SC-006 name: case 1's `twin show` naming the snapshot beside the bundle, the one `intent read | twin compile` gives; case 4's create holding case 2's snapshot and bundle; case 5's rebuilt twin naming no snapshot (`snapshot none`, `snapshot_id` null); case 7's plan naming three snapshot ids, the branch point's null, the create deploying `seeded`'s, and each step's sides naming the plan's; case 9's report table carrying the `snapshot` column. Add each to its case in the list's wording. per FR-029, SC-006 (partial)
  - *2026-10-27, Run 18 of the converge loop:* done, at `42cc665`. Case 1's create holds the snapshot and the `bundle_id` that `intent read | twin compile` gives, and its `twin show` names `snapshot <id>, bundle_id <id>`. Case 2's holds those `intent read --at T | twin compile` gives (beyond the task's list: `scripts/e2e.sh` line 954 asserts it). Case 4 holds case 2's snapshot and `bundle_id`. Case 5's `twin show --json` names the created twin's snapshot and the rebuilt one's none (`snapshot_id` null, `snapshot none` in the text), since the check read and compiled in the worker. Case 7's branch point has null snapshot and bundle ids; `seeded`, `third-link` and the head are taken and compiled to three snapshot ids and three bundle ids; the create deploys the plan's `seeded` snapshot and bundle, recorded in `twin.json` `9`; each step's sides, its document and the record it leaves name the plan's ids for their stages. Case 9's table carries its `snapshot` column. Each was read against the script's own lines (884–894, 954, 1039, 1081, 1210–1214, 1373–1388, 1431, 1465–1507, 2076). The one other `twin.json` `8` in the guide (line 574) is the frozen copy's, and stays.

- [X] T067 [pin] Make the glossary's **Snapshot store** say which `observed_at` a twin records, as the code and `docs/architecture.md` do, with no code changed. `docs/glossary.md` (lines 1072–1073) says "two takes of one intent keep one document, the first, and a twin built from the second records the first's `observed_at`". That holds for `twin create --snapshot`, an id or a file of a later take (`resolveSnapshot` fetches the stored document after its `Put`; US3/AC8). A `twin create --branch` or `--stage` whose take is the second records its own read's time (`runCreate`'s `ObservedAt: compiled.observedAt`; T051's note, "not the stored take's, as R-11 has it"), as §4.5's "The record names its snapshot" ("a create's own read, the stored first take for a twin from a snapshot") and `contracts/twin.schema.json`'s `observed_at` description say. Reword the sentence to that rule. per FR-029, US3/AC8 (partial)
  - *2026-10-27, Run 18 of the converge loop:* done, at `8b561de`. The entry keeps "two takes of one intent keep one document, the first", then says a twin built by `twin create --snapshot`, by its id or from a file of a later take, records the stored first take's `observed_at`, and a `twin create --branch` or `--stage` whose take is the second records its own read's time. Checked against the code: `runCreateFromSnapshot` sets `observedAt: s.ObservedAt`, the stored document's (`internal/server/create.go:210`), and the read's path sets the read's own `time.Now()` (`:361`, `:382`).

  *Run 18's checkpoint, 2026-10-27 (convergence pass 1: T065, T066, T067)*:
  - **Commits**: `1a29956` (T065), `42cc665` (T066), `8b561de` (T067), then this note. No golden moved (`git diff main -- testdata/golden` is empty), so no re-baseline commit.
  - **Gates**, on the committed tree: `make build` statically linked; `make test` uncached (`GOFLAGS=-count=1`) passed in 40.8 s wall, the load average 1.80 before and 3.57 after (`internal/cli` 37.1 s alone), under 45 s; `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `go generate ./...` left the tree unchanged; `make linkcheck` 84 files, 1,912 relative links, 0 broken.
  - **Tier 2**: none run, since no task names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` count 0.
  - **Not run, and why**: tier 3, twins and the worker are not this run's.
  - **The host**: the worker (pid 1562726) and the server (pid 1562767) read `(deleted)`: `bin/fylgja` has been rebuilt since they started, by this run's `make build` at least; neither was restarted. The change they lack is `twin create`'s help text alone, which a client prints with no server.
  - **Next**: convergence pass 2.

---

## Phase 15: Convergence

- [X] T068 [behaviour] Refuse a snapshot whose inner CTM records no `observed_at`, or one not in `snapshot.ObservedAtLayout`, before anything files it, so no entry the store cannot read back is ever written. Today `snapshot.Unmarshal` (`internal/snapshot/json.go`, step 4, line 97) fills the outer `observed_at` from the inner CTM's whatever it holds, and `check` (`internal/snapshot/snapshot.go:198`) holds the two equal but not to the layout. So `twin create --snapshot <file>` of a hand-wrapped CTM with no `envelope.observed_at`, or with `2026-10-27T18:55:42Z` (no fractional digits), passes `Unmarshal`, and `resolveSnapshot`'s `Put` writes `"observed_at": ""` (or the malformed value) under the id. The id leaves `observed_at` out, so that id is the one every valid take of the same intent hashes to: `6a8a77fc…` for `testdata/ctm/three-node.json`, found by a scratch test run through `go test -overlay`, nothing written to the tree. The store's own `Fetch` then refuses the entry (`… is not a snapshot: observed_at "" is not a UTC time with six fractional digits …`), so the create answers `operation.failed` at `resolve` rather than the CTM's fault; and every later `twin create --branch` or `--stage`, dry run, `intent read --out`, `stage plan`, `twin step` and rehearsal of that intent fails `operation.failed` at its take (`filing snapshot <id>: … is not a snapshot`) until the entry is removed by hand. The fix, in `internal/snapshot` alone, `ctm.Unmarshal` unchanged (FR-026):
  - after step 3, an inner CTM recording no `observed_at` is `*ctm.MissingError{Field: "ctm.envelope.observed_at"}`, which the server files as `data.required.missing` (the CTM's own rule, prefixed `ctm.`, as R-03 maps the inner CTM's faults and `contracts/ctm.schema.json` requires the field);
  - an inner `observed_at` not in `ObservedAtLayout` is `*InvalidError{Field: "ctm.envelope.observed_at"}`, `snapshot.invalid` (the Identifiers table's "`observed_at` not of the CTM's form");
  - `check` refuses an `ObservedAt` not in the layout, so `Marshal` and `Put` never write an entry `Unmarshal` refuses, as `Marshal`'s comment already says.

  Tests: `TestUnmarshalRefusals` gains both cases, with no outer `observed_at`; `TestMarshalRefusesABrokenSnapshot` gains an empty and a malformed `observed_at`; `fileRefusals` (`internal/server/snapshot_test.go`) gains both files, so `TestResolveSnapshotRefusesAFileByItsRules` and `TestCompileRefusesASnapshotByItsRules` hold each refused under its rule with nothing filed; and an `internal/server` test runs each refused file through `resolveSnapshot`, then `takeSnapshot` of the same intent with a proper `observed_at`, which files and returns the entry. A `twin compile --snapshot` of such a file is now refused at the file by `Unmarshal`, not by validation at compile: move any pinned object from `observed_at` to `ctm.envelope.observed_at`. Make `contracts/cli.md`'s "018: snapshots" Identifiers (`snapshot.invalid`'s row and the inner CTM's sentence) and `docs/architecture.md` §4.2's strict-reading sentence name the two refusals where they list the inner CTM's faults. per FR-003, FR-007, Edge Cases ("a snapshot whose inner CTM fails CTM 2's validation") (contradicts)
  - *2026-10-27, Run 19 of the converge loop:* done, at `f3a9ae6`. `Unmarshal`'s step 4 now holds the inner CTM's `observed_at` after the CTM's own refusals and before the id: none recorded, absent or `""`, is `*ctm.MissingError{Field: "ctm.envelope.observed_at"}` ("ctm.envelope.observed_at, the read's time, is not recorded: …"), and one not in `ObservedAtLayout` is `*InvalidError` at the same field; `check` refuses an `observed_at` not in the layout, so `Marshal` and `Put` write nothing `Unmarshal` refuses. No server code changed: `snapshotRefusal` already files the two types as `data.required.missing` and `snapshot.invalid` at their field. An outer `observed_at` beside an inner CTM recording none stays step 2's refusal, `snapshot.invalid` at `observed_at` ("none recorded"), in R-03's order. Tests: `TestUnmarshalRefusals` gains three cases (absent, empty, malformed), `TestUnmarshalRefusesInOrder` two (the links' refusal before `observed_at`'s, `observed_at`'s before the id's), `TestMarshalRefusesABrokenSnapshot` two, and `fileRefusals` two, held by `TestResolveSnapshotRefusesAFileByItsRules` and `TestCompileRefusesASnapshotByItsRules` with nothing filed; the new `TestARefusedObservedAtLeavesTheTakeOfItsIntent` (`internal/server`) takes the same intent after each refused file and fetches the entry it filed. Each new case failed with the fix stashed. No test pinned a compile of such a file, so no object moved. `contracts/cli.md`'s `snapshot.invalid` row and inner-CTM sentence, `docs/architecture.md` §4.2, `RuleSnapshotInvalid`'s comment and `InvalidError`'s doc name the two refusals. `contracts/snapshot.schema.json` is unchanged: it says the inner CTM is refused by its own rules, and `contracts/ctm.schema.json` requires `observed_at` in that pattern.

- [X] T069 [pin] Hold the snapshot store to tier 3's credential greps, as the bundle store is held, with no code changed. `scripts/e2e.sh` line 2189 scans `scan=("$OUT" "$FYLGJA_STATE_ROOT/bundles")`, and line 2190 says it searched `the run's outputs and the bundle store`. Before 018 every read's CTM, each device's rendered configuration in it, was filed beside its bundle as `<bundle_id>.ctm.json`, inside the scanned directory; since 018 the same CTM is filed under `snapshots/` (FR-006, FR-008), which no grep of the script reads. T054 searched `local/snapshots` by hand; the script does not. Add `"$FYLGJA_STATE_ROOT/snapshots"` to `scan` and to `searched`, as `bundles/` holds every bundle the host compiled, and leave the marker grep (line 2231) as it is: a snapshot carries the artifact marker by design, as a staged bundle does. Make the header's and any guide's sentence on what the greps search name the snapshot store. Check offline, as T047 did: `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean; the extracted `no_credential` line fails with `LEAK` over a scratch copy of a snapshot holding a planted value, and passes over `local/snapshots`, printing file names alone. per Constitution X, FR-006 (partial)
  - *2026-10-27, Run 19 of the converge loop:* done, at `48589cd`. `scan` adds `"$FYLGJA_STATE_ROOT/snapshots"`, `searched` reads "the run's outputs, the bundle store and the snapshot store", and the comment above them says why both stores are searched for the credentials and neither for the marker; the marker grep is unchanged. The header now says no token or password is found in the outputs, the bundle store or the snapshot store, and `docs/development.md`'s tier-3 paragraph names both stores, with "a read's snapshot" in place of "a read's CTM". Checked offline: `shellcheck` clean. The extracted `no_credential` ran under plain `bash`, whose `grep` is `/usr/bin/grep` (this session's own `grep` is a ugrep wrapper that skips git-ignored files, `local/` among them). It found a planted value in a scratch copy of a snapshot (`LEAK`, the file name alone, exit 1). Over `local/snapshots`, it found none of six values from `local/.env` (the Infrahub token, the API's token, the SR Linux password, the secret key, the agent token and the admin password) and printed nothing. The store's 67 entries were all read: `grep -rl snapshot_version` lists 67. The EOS login's contextual grep was not run by hand.

- [X] T070 [pin] Bring `stage plan`'s help to 018, and name the snapshot in `twin step`'s and `twin rehearse`'s, with no code path changed. `internal/cli/stages.go` lines 66–73, `stage plan`'s Long help, says the plan files "each bundle and its CTM in the store" and that the server "reads, compiles and files them in its bundle store". Since 018 no build files a CTM beside a bundle (FR-008), and the plan takes and files each compiled stage's snapshot in the snapshot store and prints its `snapshot_id` above its `bundle_id` (FR-014, FR-022). Word it as `twin create`'s Long help words the take since T065: each stage read, its snapshot taken and filed, compiled, its bundle filed, both stores named. Name the snapshot the server takes in `twin step`'s Long help and `--dry-run` flag (`internal/cli/step.go` lines 33 and 57, "resolves, reads, compiles and files the target") and in `twin rehearse`'s Long help (`internal/cli/rehearse.go` line 29, "resolves, reads, compiles and files every stage first"), per FR-011 and FR-012; `runStagePlan`'s and `runTwinStep`'s doc comments (`stages.go:102`, `step.go:63`) move with them. Pin in `internal/cli`, as `TestCreateHelpNamesTheServersTake` does, that `stage plan --help` names the snapshot and no longer says "its CTM", and that `twin step --help` and `twin rehearse --help` name the snapshot. per FR-008, FR-014, FR-011, FR-012 (contradicts)
  - *2026-10-27, Run 19 of the converge loop:* done, at `611cd0f`. `stage plan`'s Long help says the API's server resolves each stage, reads it, takes the snapshot of what it read and files it in its snapshot store, compiles it and files the bundle in its bundle store, and prints the stage's `snapshot_id` above its `bundle_id`; it needs Infrahub and its two stores. `twin step`'s says the server resolves the target, reads it, takes the snapshot, compiles it and files the snapshot and the bundle, as stage plan builds a stage, and its `--dry-run` flag reads "resolve and read the target, take and file its snapshot, compile and file its bundle, check the host and read containerlab's plan; start no run". `twin rehearse`'s says the server builds every stage first, as stage plan does, taking each one's snapshot. The two doc comments moved with them. "Each side naming its snapshot" was left out of the step's help, since a `twin.json` `8` record's from side names none. `TestStageHelpsNameTheServersTake` (`internal/cli/stage_test.go`) pins each help whole, flags included, its whitespace folded, and that "its CTM" and the old phrases are gone. `TestWorkHelpTextsNameTheServer`'s plan and step phrases moved to the new wording. Both failed with the old help. `contracts/cli.md` line 243 quotes M12's help as M13's history, and stays.

- [X] T071 [pin] Make the glossary's **Step (of a run)** and two comments in `internal/provision` say that a create's read and compile are the server's, with no code changed. `docs/glossary.md` lines 1141–1147 give a provisioning run's steps as "read, compile, host check, stage, deploy, …", and the command's own steps, "taken by the *server* before any run starts", as `start`, `verify` and `resolve` alone. Since 018 every provision a build of this tree starts begins at the host check, its `read` and `compile` the server's, as a step's and a rehearsal's already were (FR-009, FR-011, FR-012); only a following check's run reads and compiles (FR-013), beside the recorded histories. `internal/provision/workflow_provision.go:18`'s first sentence ("Provision is the provisioning run: read, compile, check the host, …") and `activities.go:166–168`'s `ReadIntent` comment ("so a create that stops here reports M1's findings under M1's identifiers") say a create reads in its run. Reword the three to that rule, as `docs/architecture.md` §4.4 and the glossary's **`provision` (workflow)** entry word it. per FR-009, FR-029 (partial)
  - *2026-10-27, Run 19 of the converge loop:* done, at `160b9c0`. **Step (of a run)** lists a provisioning run's steps from the host check. It names `start`, `verify`, `resolve`, `read` and `compile` as the server's, taken before any run starts, since every provision begins at the host check from 018, as a step's and a rehearsal's do. Only a following check's run reads and compiles, and a pre-018 history begins with those two, kept so it replays. `Provision`'s doc comment begins at the host check, says its read and compile are the server's or a following check's, and says an input from intent with no `BundleID`, which no build of this tree starts, reads and compiles first so that the old histories replay. `ReadIntent`'s comment names a following check where it said a create, and says a provision schedules it only in a pre-018 history. `workflow_provision_test.go:36` still lists read and compile, since it runs that kept branch.

  *Run 19's checkpoint, 2026-10-27 (convergence pass 2: T068, T069, T070, T071)*:
  - **Commits**: `f3a9ae6` (T068), `48589cd` (T069), `611cd0f` (T070), `160b9c0` (T071), then this note. No golden moved (`git diff main -- testdata/golden` is empty), so no re-baseline commit.
  - **Gates**, on the committed tree: `make build` statically linked; `make test` uncached (`GOFLAGS=-count=1`) passed. The first run took 48.6 s wall (load average 2.03 before, 3.14 after) because `internal/findings`' change rebuilt nearly every test binary. The second, with the build cache warm, took 41.0 s (load 2.73, then 3.15), under 45 s, `internal/cli` 36.6 s alone. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `go generate ./...` left the tree unchanged; `make linkcheck` 84 files, 1,913 relative links, 0 broken; `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean.
  - **Tier 2**: none run, since no task names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` count 0.
  - **Not run, and why**: tier 3, twins and the worker are not this run's.
  - **The host**: the worker (pid 1562726) and the server (pid 1562767) still read `(deleted)`. Neither was restarted: a loop session holds no node logins. The server lacks T068: until it is restarted from this build, it still files a `twin create --snapshot <file>` whose inner CTM records no `observed_at`, or one not of the CTM's form. The worker lacks only T071's comments; T070's help is the client's.
  - **Next**: convergence pass 3.

---

## Phase 16: Convergence

- [X] T072 [behaviour] Make a create's text answer name the snapshot it filed when the compile, or the bundle's filing, then refuses or fails, as its `--json` document already does. `readTakeCompile` (`internal/server/create.go:375–385`) files the snapshot before the compile, and `compiledRead.carried` puts its id on the document (`TestRefusedCompileKeepsTheSnapshot`). But the `snapshot_id <id>  stored: <path>` line is printed only once the compile and the filing succeeded: `runCreate` (lines 144–145), `runCreateFromSnapshot` (lines 218–219) and `dryRunReport` (`internal/server/dryrun.go:70–72`). So a `twin create --branch` or `--stage`, or its `--dry-run`, whose read is clean and whose compile is refused prints only the findings and their summary on stderr. Two examples: a CTM naming a package this server lacks, as `TestRefusedCompileKeepsTheSnapshot` builds, or a compile rejection the read does not make. The text answer then names neither the snapshot that FR-010 says is left filed "and named in the answer", nor the store path that FR-014 says a dry run prints for each id it files. `twin create --snapshot <file>`, whose id the server computes, does the same when its compile is refused. Print the `snapshot_id … stored:` line (`snapshotStoredLine`) on stdout whenever the take completed, or `resolveSnapshot` filed or fetched the entry, and the compile or the bundle's filing then refused or failed. Leave the success paths' order unchanged (the snapshot's line above the bundle's, R-09), and every JSON document too. Print nothing for a refused read, which files nothing (FR-010), or for a snapshot refused at `resolve`. Pin it in `internal/server`, in text mode over `fakeRead` beside `TestRefusedCompileKeepsTheSnapshot`: the line appears once and names the filed entry's path. Pin it in `internal/cli` through the harness, for `twin create --branch`, `--dry-run` and `twin create --snapshot <file>`, each refused at compile. Say it in `contracts/cli.md`'s "018: snapshots" create paragraph, where "a refused compile leaves the snapshot filed, since its CTM validated" gains that its `snapshot_id … stored:` line names it. per FR-010, FR-014 (partial)
  - *2026-10-27, Run 20 of the converge loop:* done, at `49f7615`. `compileAndFile`, which only the create's two paths call, now prints the snapshot's stored line, through a new `compiledRead.refused`, and then carries the document as before. It does so on each of its three exits: the compile refused, the bundle's filing refused (`bundle.id.mismatch`), and the filing failed (`operation.failed`). So a `twin create --branch` or `--stage`, its dry run, and a create from a snapshot (an id fetched or a file filed) print the line once and alone on stdout, with the refusal on stderr. A refused read, a refused take (`snapshot.id.mismatch` at compile) and a snapshot refused at `resolve` return before it and print nothing. The success paths' order and every JSON document are unchanged. `TestARefusedCompileNamesTheSnapshotInText` pins it twice. In `internal/server`, over `fakeRead`: a compile refused for a package this server lacks, a corrupt entry under the fixture's bundle id, a `bundles` that is a file, a stored snapshot's refused compile through `runCreate` with its id, and a refused read printing nothing. In `internal/cli`, through `runRoot` and `executeTwin`: `--branch` and `--branch --dry-run` over a corrupt entry under the head's bundle id, `--snapshot <file>` naming a package the server lacks, and an unknown id at `resolve` printing nothing; the line names the one entry `snapshots/` holds, which the `--json` document names. Every positive case failed with the fix stashed. `contracts/cli.md`'s create paragraph says the line names the snapshot, a refused or failed filing of the bundle included, and "The text" says when it prints alone and when neither line prints.

  *Run 20's checkpoint, 2026-10-27 (convergence pass 3: T072)*:
  - **Commits**: `49f7615` (T072), then this note. No golden moved (`git diff main -- testdata/golden` is empty), so no re-baseline commit.
  - **Gates**, on the committed tree: `make build` statically linked; `make test` uncached (`GOFLAGS=-count=1`) passed. The first run took 47.3 s wall (load average 1.57 before, 2.54 after), rebuilding the test binaries of the two changed packages. The second, with the build cache warm, took 40.8 s (load 2.31, then 3.79), under 45 s, `internal/cli` 36.5 s alone. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `go generate ./...` left the tree unchanged; `make linkcheck` 84 files, 1,913 relative links, 0 broken.
  - **Tier 2**: none run, since no task names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` count 0.
  - **Not run, and why**: tier 3, twins and the worker are not this run's.
  - **The host**: the worker (pid 1562726) and the server (pid 1562767) still read `(deleted)`. Neither was restarted: a loop session holds no node logins. The server lacks T068 and T072: until it is restarted from this build, a create refused at compile prints no `snapshot_id … stored:` line. The worker lacks nothing of this run's.
  - **Seen, not tasked**: a create's dry run whose host check cannot run (`lab.CheckHost` returning an error, or the manifest unreadable after it) has filed the snapshot and the bundle, but `dryRunReport`'s `failAt` returns before either stored line prints, and nothing carries the ids to the document, so it names neither (read in `internal/server/dryrun.go:47–60`, not run). FR-014 says a dry run prints each id it files with its store path. Left for convergence pass 4 to weigh.
  - **Next**: convergence pass 4.

---

## Phase 17: Convergence

- [X] T073 [behaviour] Make a create's dry run whose host check cannot run name the snapshot and the bundle it filed, in its text answer and in its document, as the real create's answer does. `runCreateDryRun` (`internal/server/create.go:307–315`) and `runCreateFromSnapshot`'s dry run (`:214–216`) take and file the snapshot, compile and file the bundle, then call `dryRunReport` (`internal/server/dryrun.go:45`). Its two `failAt` exits come before the stored lines print (lines 70–73): `lab.CheckHost` returning an error (lines 47–50), and `manifestSummary` failing (lines 57–60). `CheckHost` errors when containerlab's inspect fails, or under `FYLGJA_HOST_MEMORY_MB=lots` (`lab.EnvHostMemoryMB`), which `internal/cli/twin_step_test.go:1418` uses to make a step's host check fail. Each exit returns a document built fresh, with no `snapshot_id`, no `bundle_id` and none of the read's and compile's findings in `prior`. So the operator is told of neither entry, though both are filed and kept for ever. Three statements say otherwise. `contracts/cli.md`'s "018: snapshots", "The text", says "`twin create` and its dry run print, before the run's `start` (or the dry run's report)", both stored lines. `contracts/findings.schema.json`'s `snapshot_id` is present on "twin.create and its dry run (once the take completed)". Its `bundle_id` is present on "twin.create … (any status once compile completed)". The real create's run failure carries all three, through `compiledRead.carried`. The fix, in `dryRunReport`:
  - on either exit, print the snapshot's stored line (`snapshotStoredLine`, when `snap` is non-nil) and the bundle's (`bundleStoredLine`) on stdout, in the success path's order, with the failure on stderr;
  - carry `snapshot_id`, `bundle_id` and `prior` on the failure's document, as `stepTo` carries its list through `withFound`;
  - leave the success path's text and document unchanged, byte for byte, and change nothing a refused read, a refused take, a snapshot refused at `resolve` or T072's compile exits print.

  `twin provision --dry-run` shares `dryRunReport` and passes no snapshot, so on the same exits it prints its bundle's line alone and carries its `bundle_id`; `bundle_id`'s description ("twin.provision (any status …)") allows that. Pin it in `internal/server`, over `fakeRead` beside `TestARefusedCompileNamesTheSnapshotInText`, with `t.Setenv(lab.EnvHostMemoryMB, "lots")`. Cover `--branch --dry-run` and `--snapshot <file> --dry-run`. In text, each stored line appears once and names the one entry `snapshots/` and `bundles/` each hold. In `--json`, status error, `operation.failed` at `host_check`, `snapshot_id` and `bundle_id` naming those entries, and the fake read's warning, when it gives one, leading the findings. Pin it in `internal/cli` through the harness, for `twin create --branch … --dry-run`. Each positive case must fail with the fix stashed. Say it in `contracts/cli.md`'s "The text" paragraph: a dry run whose host check cannot run prints both lines and names both ids. per FR-014, FR-010 (partial)

  - *2026-10-27, Run 21 of the converge loop:* done, at `d768b40`. `dryRunReport` sends both of its `failAt` exits, the host check erring and the manifest unreadable after it, through a new local `failed`. It prints the snapshot's stored line, when the dry run filed one, then the bundle's, on stdout, and puts `snapshot_id` and `bundle_id` on the failure's document, with `prior` leading its findings through `withFound`. So a `twin create --branch` or `--stage` dry run, and a `--snapshot` one, whose host check cannot run print both lines alone, with `operation.failed` at `host_check` on stderr, and name both ids. `twin provision --dry-run` prints and names its bundle alone. The success path and every earlier exit are unchanged. `TestADryRunWhoseHostCheckCannotRunNamesWhatItFiled` pins it twice, under `FYLGJA_HOST_MEMORY_MB=lots`. In `internal/server`: `--branch --dry-run` over `fakeRead` given a read warning (`artifact.interface.unrepresented`), which leads the findings at `read`; `--snapshot <file> --dry-run` through `runCreate`; and the provision dry run over the golden bundle. In text each stored line names the one entry its store holds; in `--json` the document is status error, ends with `operation.failed` at `host_check`, names both ids and validates against the current contract. In `internal/cli`, through `runRoot` and `executeTwin`: `twin create --branch fylgja-fixture --dry-run` prints the head's two stored lines alone, the failure on stderr, and dials nothing. Every positive case failed with the fix stashed. The manifest exit shares the path but no test reaches it, since the host check has just read the same manifest. `contracts/cli.md`'s "The text" says it, the provision dry run's bundle line included.

- [X] T074 [operator] Settle FR-024's and US5's sentence that `rehearsal.steps.none` "still judges by bundle equality", which neither the code nor any contract has ever done. `spec.md` line 236 (US5's prose) and line 434 (FR-024, "`rehearsal.steps.none` MUST still judge by bundle equality") state that rule. 015's contract defines the rule by count. `contracts/cli.md` line 564 files it "when it is the only one" compiled, and line 705 says "one stage alone compiled". `RuleRehearsalStepsNone`'s comment (`internal/findings/finding.go:224`) and `rehearsalStages` (`internal/server/rehearse.go:167`, `len(rows)-baseline == 1`) do the same. T021's note (Run 7) found the rule never judged by bundle equality. It built what US5 scenario 5 asks: the rule judges "as before", and the two rows show their snapshot ids. `TestSnapshotColumnBeforeBundle` holds two adjacent stages of one bundle id and two snapshot ids rehearsed with no `rehearsal.steps.none` filed. No converge pass can satisfy FR-024 as written without changing 015's rule. The operator's choice is one of two:
  - (a) amend the two sentences in `spec.md` to say the rule judges as before, by whether one stage alone compiled, with no code changed;
  - (b) decide that two adjacent stages of one bundle are a step to nowhere. That is a new behaviour and a change to 015's contract, so it needs a decision entry before any task builds it.

  Record the answer in this task's note. per FR-024, US5/AC5 (contradicts)
  - *2026-10-27 23:35Z, the operator's answer to the attended loop's question 1 (pass 4): "1a".* The rule stays 015's, by whether one stage alone compiled, and no code changes. `spec.md`'s US5 prose and FR-024 are amended to say so, in the attended session's commit, in the wording the operator approved.

  *Run 21's checkpoint, 2026-10-27 (convergence pass 4: T073)*:
  - **Commits**: `d768b40` (T073), then this note. No golden moved (`git diff main -- testdata/golden` is empty), so no re-baseline commit.
  - **Gates**, on the tree committed at `d768b40`: `make build` statically linked; `make test` uncached (`GOFLAGS=-count=1`) passed. The first run took 46.4 s wall (load average 2.20 before, 2.92 after), rebuilding the test binaries of the two changed packages. The second, with the build cache warm, took 40.8 s (load 2.68, then 2.97), under 45 s, `internal/cli` 36.3 s alone. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `go generate ./...` left the tree unchanged; `make linkcheck` 84 files, 1,913 relative links, 0 broken.
  - **Tier 2**: none run, since no task names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` count 0.
  - **Not run, and why**: tier 3, twins and the worker are not this run's. T074 stays unchecked: it is the operator's choice between (a) and (b), which neither `spec.md`, `plan.md`, `research.md` nor `docs/decisions.md` settles.
  - **The host**: the worker (pid 1562726) and the server (pid 1562767) still read `(deleted)`. Neither was restarted: a loop session holds no node logins. The server lacks T068, T072 and T073: until it is restarted from this build, a dry run whose host check cannot run prints neither stored line and names neither id. The worker lacks nothing of this run's.
  - **Next**: T074, the operator's; then convergence pass 5.

---

## Phase 18: Convergence

- [X] T075 [pin] Bring four sentences in three tracked documents to 018's create, which the server reads for, with no code changed. (1) `README.md` line 739, "The stages on their own", opens "`twin create` runs every stage inside one durable run." Since 018 the API's server resolves the stage, reads, takes and files the snapshot, compiles and files the bundle before any run, and one durable run, `fylgja-provision`, does the rest from the host check (FR-009), as `twin create --help` says since T065. Reword it so, keeping the paragraph's point that each stage is also a command. (2) `docs/development.md` line 164, the environment table's `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` row, says the server reads "for every command that reads intent (`intent read`, `schema check`, `stage list` and `stage plan`, a create's resolution and dry run, `twin step`'s target)" and the worker "(the read step runs there)". Since 018 the server reads for every create, not its dry run alone, and for `twin rehearse`'s plan (FR-009, FR-012). The worker's read step runs only in a following check's run (FR-013), beside the recorded histories. Before rewording, read each `intent.StageReaderFromEnv` and `stage.Read` caller in `internal/server` and `internal/provision`, so the row names exactly what dials Infrahub on each side. (3) `docs/development.md` line 368, the layout's `contracts/` line, lists "every JSON schema (findings, show, twin, manifest, CTM, PSP, step, verify, stages, API frames)". It names neither `snapshot` (018) nor `rehearsal` (015). T049's note left this for T057, and it is still missing; add both. (4) `docs/glossary.md` line 444, the **Frame** entry, gives "`files` (the CTM or a bundle, base64)". Since 018 `intent read`'s `files` frame carries the snapshot (`snapshot.json`, `internal/server/read.go:229`; FR-020), so say "a snapshot or a bundle". Check: `make linkcheck` is clean, and `/usr/bin/grep -n 'inside one durable run\|the read step runs there\|the CTM or a bundle' README.md docs/development.md docs/glossary.md` finds none of the old phrases. per FR-029, FR-009, FR-020 (partial)
  - *2026-10-27, Run 22 of the converge loop:* done, at `15ae797`. (1) The README's "The stages on their own" now says `twin create` runs every stage for the operator: the server reads the branch, takes and files the snapshot, compiles it and files the bundle, then one durable run boots the twin from the host check on; each stage is also a command. (2) Read first: the server dials Infrahub through `intent.StageReaderFromEnv` (`resolveStage`, `runStageList`, `planStages`, `stagesVerified`, `twin step`'s target), `intent.FromEnv` (`intentStamper`, `schema check`) and `stage.Read` (`intent read`, a create's read and dry run); `twin rehearse` plans through `planStages` and reads the stages again through `stages.List` once its run has closed (`rehearsing.after`); `runCreateFromSnapshot` loads packages and reads no intent. On the worker `stage.Read`'s one caller is `ReadIntent`, which the reconcile schedules and a provision only in a history recorded before 018. The row says so: the server for `intent read`, `schema check`, `stage list` and `stage plan`, every `twin create` from a branch or a stage and its dry run, `twin step`'s target and `twin rehearse`'s plan and closing read, never `twin create --snapshot`; the worker for a following check's read alone, and a provision recorded before 018. (3) The layout's `contracts/` line names `snapshot` and `rehearsal` among the JSON schemas, so it lists the twelve `contracts/` holds. (4) The glossary's **Frame** gives `files` "a snapshot or a bundle". `make linkcheck` 84 files, 1,913 relative links, 0 broken; the check's grep finds none of the old phrases.

- [X] T076 [pin] Bring three contracts' top-level `description` strings to 018, with no keyword changed. (1) `contracts/ctm.schema.json`'s description opens "Written by `fylgja intent read`, read by `fylgja twin compile`, and used as a fixture" and ends "so a CTM file holds configuration and lives only in the bundle store". Since 018 `intent read --out` writes a snapshot that wraps the CTM, and `twin compile --snapshot` reads one, refusing a bare CTM as `snapshot.version.unsupported` (FR-019, FR-020). The CTM's configuration lives in the snapshot store, since the bundle's sidecar is retired (FR-008). Reword both sentences to that, and add a closing "018:" sentence in the file's history style: CTM `2` unchanged and wrapped by the snapshot. (2) `contracts/api.schema.json`'s description has a sentence for each of 014, 015 and 017 and none for 018. It also says "The CTM, the bundle and a support package cross inside $defs/file … (ctm.schema.json, manifest.schema.json, psp.schema.json)". Since 018 the snapshot crosses there in the CTM's place: in `twin.compile`'s request, as `twin.create --snapshot`'s one file, and in `intent.read`'s `files` frame, each validated by `snapshot.schema.json`. `twin.create` and `twin.compile` also take `snapshot`, and `twin.compile` no longer takes `ctm` (FR-027, as `contracts/api.md`'s "018: snapshots" says). Name the snapshot among what crosses, and add the 018 sentence: the version stays `1`, as the earlier sentences give their reasons. (3) `contracts/twin.schema.json`'s description says the record carries "observed_at when the run performed a read and an explicit statement that it is unknown when it did not". Since 018 no create's run reads, and the `observed_at` property's own description already says the run's input carried a read's time. Bring the top-level sentence to the property's wording, leaving the per-version history sentences as they are. Only the three `description` strings change. Every keyword, `$id`, version constant and frozen copy under any `testdata/contracts/` stays byte for byte (FR-026; `git diff --stat -- '*/testdata/contracts/*'` is empty). Check: each file parses (`python3 -m json.tool`), and `go test -count=1 ./internal/ctm ./internal/snapshot ./internal/api ./internal/lab ./internal/findings ./internal/server ./internal/cli` passes, `TestFrozenContractCopiesAgree` included. per FR-027, FR-029 (partial)
  - *2026-10-27, Run 22 of the converge loop:* done, at `c484d67`. (1) `ctm.schema.json` opens "Written inside a snapshot by `fylgja intent read --out`, read inside one by `fylgja twin compile --snapshot`, and used as a fixture", and its M5 sentence ends that a CTM is kept only inside its snapshot, in the snapshot store, the bundle's CTM sidecar retired; a closing "018 (D-061):" sentence says `ctm_version` stays `2`, the snapshot wraps it unchanged as its body's `ctm`, and a bare CTM where a snapshot is read (`twin compile --snapshot`, `twin create --snapshot`) is `snapshot.version.unsupported`, as `snapshotRefusal` files it. (2) `api.schema.json`'s M13 sentence names "The snapshot (the CTM before 018)" and `snapshot.schema.json` among what crosses `$defs/file`, and a closing "018:" sentence names the three places it crosses, `snapshot` on `twin.create` and `twin.compile`, `ctm` gone from `twin.compile`, and why the version stays `1`. (3) `twin.schema.json`'s top-level sentence says `observed_at` is set "when the run's input carried a read's time (a create's read, a snapshot's stored take, or a check's)", the property's own wording; the history sentences are unchanged. Each file parses (`python3 -m json.tool`), and each, loaded with its `description` removed, equals the file before the edit, so no keyword, `$id` or constant moved; `git diff --stat -- '*/testdata/contracts/*'` is empty. `go test -count=1` over the seven named packages passed, `TestFrozenContractCopiesAgree` included.

- [X] T077 [pin] Bring nine Go comments, which say a create's run reads, name the CTM where the snapshot crosses, or name `8` as the record this build writes, to 018. Change no code and no message string. (1) `internal/cli/send.go:24`, `handlers.files`: "the CTM or the bundle". Make it the snapshot or the bundle, as its server-side counterpart `internal/server/call.go:121` says. (2) `internal/api/wire.go:130`, `Request.Files`, says "on twin.compile, twin.provision and psp.validate", leaving out `twin.create`'s one snapshot file beside a `--snapshot` path (`snapshotFiles`, `internal/server/snapshot.go:56`). (3) `internal/server/validate.go:85–86`, `loadFailureAt`, says "twin create loads packages for its read, as the run's read step does". From 018 the create's run has no read step: the server loads the packages before its own read, or before the compile for `--snapshot` (`internal/server/create.go:191–193`). (4) `internal/findings/finding.go:252`, `RuleCTMVersionUnsupported`'s comment, reads "no step: the CTM file; twin compile was given a CTM of another version". From 018 its one filer is `snapshotRefusal` (`internal/server/snapshot.go:177`), for a snapshot's inner CTM. That filing happens at `twin compile --snapshot`, with no step, and at `twin create --snapshot <file>`, at `resolve`. Its object is the snapshot file, and a bare CTM is `snapshot.version.unsupported`. (5) `internal/provision/types.go:89`, `ProvisionInput.Branch`, says "intent: the branch to read". (6) `:114`, `Scope`, says "the scope the run's read is made under". A run this build starts reads nothing: the server read, or the snapshot carries the reference. The run records both as provenance, and the following's checks read under them; only a pre-018 history's run reads under them, as `Provision`'s doc comment says since T071. (7) `internal/server/step.go:193`, `stepScopeUnknown`'s doc, says "a worker of this build writes 8"; it writes `9` (`lab.TwinVersion`). (8) The same doc's line 181, and (9) `internal/findings/finding.go:179`'s `RuleStepTwinUnsteppable` comment, say "an 8 naming a scope …". The rule is a record of `8` or later (`scopeRecorded`, `internal/server/show.go:436–439`). Leave `stepScopeUnknown`'s refusal message, "which twin.json 8 cannot hold", as it is. Check: `make build` and `make lint` are clean, and the diff touches comment lines alone. per FR-029 (partial)
  - *2026-10-27, Run 22 of the converge loop:* done, at `abb356d`. (1) `handlers.files` says "the snapshot or the bundle", as `call.files` does. (2) `Request.Files` names `twin.create`'s one snapshot file beside a `--snapshot` that is a path. (3) `loadFailureAt` says a create loads packages before the server's own read, at read, or before the compile for `--snapshot`, at compile, since from 018 its run has no read step. (4) `RuleCTMVersionUnsupported`'s comment says no step at `twin compile --snapshot`, resolve at `twin create --snapshot <file>`, the snapshot file the object, its inner CTM of another version, and a bare CTM `snapshot.version.unsupported`. (5) `ProvisionInput.Branch` is the branch the server read, or the snapshot's, provenance the following's checks read, which only a run recorded before 018 reads. (6) `Scope` likewise, the read's scope only in a history recorded before 018. (7) `stepScopeUnknown`'s doc ends "a worker of this build writes 9". (8) Its "No build of this tree writes an 8 with another scope" reads "a record of 8 or later", line 181's own clause already saying "of 8 or later"; the sentence's next lines are re-wrapped to its width. (9) `RuleStepTwinUnsteppable`'s comment says "one of 8 or later naming a scope". The refusal message "which twin.json 8 cannot hold" is unchanged. Every changed diff line is a comment, the inline ones beside unchanged code; `gofmt -l` empty, `make build` and `make lint` clean.

  *Run 22's checkpoint, 2026-10-27 (convergence pass 5: T075, T076, T077)*:
  - **Commits**: `15ae797` (T075), `c484d67` (T076), `abb356d` (T077), then this note. No golden moved (`git diff main -- testdata/golden` is empty), so no re-baseline commit.
  - **Gates**, on the tree committed at `abb356d`: `make build` statically linked; `make test` uncached (`GOFLAGS=-count=1`) passed. The first run, before the commits on the same edits, took 46.8 s wall (load average 4.30 before, 4.16 after), rebuilding the test binaries of the changed packages. The second, on the committed tree with the build cache warm, took 41.3 s (load 2.79, then 3.43), under 45 s, `internal/cli` 36.9 s alone. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; `go generate ./...` left the tree unchanged; `make linkcheck` 84 files, 1,913 relative links, 0 broken.
  - **Tier 2**: none run, since no task names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` count 0.
  - **Not run, and why**: tier 3, twins and the worker are not this run's, and no task needed them.
  - **The host**: the worker (pid 1562726) and the server (pid 1562767) still read `(deleted)`. Neither was restarted: a loop session holds no node logins. This run changed comments and documents alone, so neither lacks anything of it; the server still lacks T068, T072 and T073 until it is restarted from this build.
  - **Seen, not tasked**: `ctm.schema.json`'s v1 sentence still places `ctm.version.unsupported` and `data.required.missing` "at twin compile" alone; `twin create --snapshot <file>` files both too, at `resolve`, the latter's object prefixed `ctm.` as `snapshot.schema.json` says (read in `internal/server/snapshot.go:132–133` and `:157–182`, not run). T076 asked for the opening and closing sentences alone, so it was left for convergence pass 6 to weigh.
  - **Next**: convergence pass 6.

---

## Phase 19: Convergence

- [ ] T078 [behaviour] Refuse `twin create --snapshot <path>` beside a conflicting flag by its guard, whether or not the file can be read, and refuse an explicit empty `--snapshot=` naming the flag. Today the client's `runCreate` (`internal/cli/create.go:122–131`) reads a non-id `--snapshot` before `send`, so an unreadable file is the client's `operation.failed` before the server's `snapshotGuards` (`internal/server/create.go:180`) can run. Probed with a scratch binary and `FYLGJA_API_ADDRESS=127.0.0.1:1`: `twin create --snapshot ./typo.json --interval 1m` answers `rejection operation.failed twin.create: reading snapshot: open ./typo.json: no such file or directory`, exit 2, where FR-016 says `follow.flags.conflict`. `--snapshot ./typo.json --branch b` answers the same, where FR-018 says `snapshot.flags.conflict` naming `--branch`. `twin create --snapshot=` answers `reading snapshot: open : no such file or directory`, which names no argument, against the Edge Case ("refused by the client before any connection, naming the argument"). `runCompile` (`internal/cli/compile.go:54–62`) sets the precedent: it holds its read back so that the server's refusals keep their order. The fix:
  - the client reads the file only when none of `--branch`, `--stage`, `--at`, `--scope` and `--interval` is given. When one is, it sends `snapshot` with no file.
  - the server's `runCreate` (`internal/server/create.go:59–70`) runs `snapshotGuards` before `snapshotFiles` whenever `fromSnapshot()`, so a request that names a snapshot path and a conflicting flag, and carries no file, gets its guard's refusal rather than "carries no file". Every guard stays exit 2 at `start`, and nothing else changes order.
  - an explicit empty `--snapshot=` with no conflicting flag is the client's refusal before any connection, `operation.failed`, exit 2, naming `--snapshot` as given empty. Beside a conflicting flag, the guard answers.

  Pin it in `internal/cli` through the harness, beside `TestSnapshotFlagConflicts`. Each of these must reach no request: `--snapshot <absent file> --interval 1m` is `follow.flags.conflict`; `--snapshot <absent file>` beside each of `--branch`, `--stage`, `--at` and `--scope` is `snapshot.flags.conflict` naming that flag; `--snapshot=` alone is refused naming `--snapshot`; `--snapshot= --at T` is `snapshot.flags.conflict` naming `--at`. Pin in `internal/server` that `runCreate` with a path, `branch` set and no file answers `snapshot.flags.conflict`. Each positive case must fail with the fix stashed. Say the order in `contracts/cli.md`'s "018: snapshots", where the client's rules for a snapshot file are given. per FR-016, FR-018, Edge Cases ("`--snapshot <arg>` that is neither a readable file nor an id") (partial)

- [ ] T079 [pin] Make five records name every place, and the right object, for the inner CTM's two refusals, and make two contracts' `snapshot_id` descriptions name every case. Change `description` strings and prose only. Since T068, `snapshotRefusal` (`internal/server/snapshot.go:157–182`) files them on two paths: `twin compile --snapshot`, with no step (`internal/server/compile.go:58–61`), and `twin create --snapshot <file>`, at `resolve` (`snapshot.go:130–133`). Its `ctm.version.unsupported` names the snapshot file (`snapshot.go:177`, pinned as `"snap.json"` at `internal/server/snapshot_test.go:177`; R-03 says "on the file given"). Only `data.required.missing` has its object prefixed `ctm.` (`internal/snapshot/json.go:89–90`).
  - Three records place both refusals at `twin compile` alone. (1) `contracts/ctm.schema.json`'s description gives "ctm.version.unsupported at twin compile" and "data.required.missing at twin compile", pass 5's "Seen, not tasked". (2) `docs/architecture.md` lines 410–411. (3) `docs/glossary.md` lines 300–302, the **CTM** entry.
  - Four sentences say, or can be read to say, that `ctm.version.unsupported`'s object is prefixed `ctm.`. (4) The glossary's own "(`ctm.version.unsupported`, the object prefixed `ctm.` inside a snapshot)". (5) `contracts/snapshot.schema.json`'s description, "the inner CTM is refused by its own rules, the object prefixed ctm.". (6) `contracts/cli.md` lines 1232 and 1257. (7) `docs/architecture.md` line 438.

  - Two `snapshot_id` descriptions list too few cases. (8) `contracts/stages.schema.json:241`, `plan_stage`'s `snapshot_id`, is "null when the stage was refused at resolution or read". `build` (`internal/stages/plan.go:271–279`) also leaves it null when the take itself is refused or fails at compile (`snapshot.id.mismatch`, `operation.failed`), and names it when the compile is refused after the take. (9) `contracts/findings.schema.json:95`'s `snapshot_id` is present on "twin.create and its dry run (once the take completed)". `twin create --snapshot` takes nothing, but `compiledRead.carried` (`internal/server/create.go:433–446`) names the id on every exit once `resolveSnapshot` has fetched or filed the entry.

  Word each to the rule. `ctm.version.unsupported` names the snapshot file. `data.required.missing` names its field prefixed `ctm.`. Each `snapshot_id` description names every case the code covers. No keyword, `$id` or version constant moves, and no frozen copy under any `testdata/contracts/` changes (`git diff --stat -- '*/testdata/contracts/*'` is empty). Check: each JSON file parses, and loaded with its `description` removed equals the file before the edit. `go test -count=1 ./internal/ctm ./internal/snapshot ./internal/stages ./internal/findings ./internal/server` passes, `TestFrozenContractCopiesAgree` included. `make linkcheck` is clean. per FR-003, FR-022, FR-027, FR-029 (partial)

- [ ] T080 [pin] Bring four sentences in the README, the architecture and tier 3's script to 018, with no code changed.
  - (1) `README.md` lines 698–699 say "`--dry-run` on `create` and `provision` reads, takes and files the snapshot, compiles and files the bundle and checks the host". A provision dry run reads nothing, takes no snapshot and compiles nothing: `internal/server/provision.go:83` passes `nil` for both to `dryRunReport`, and its help says "verify, file the bundle and check the host". A `twin create --snapshot … --dry-run` reads nothing (`internal/server/create.go:214–216`). Give each its own clause.
  - (2) `README.md` lines 768–769 say "a refused read or compile writes nothing". Since 018 a compile refused after a clean read leaves the snapshot filed and names it (FR-010; `readTakeCompile` and `compileAndFile`, `internal/server/create.go:372–413`; `contracts/cli.md`'s create paragraph). Make it "a refused read writes nothing; a refused compile leaves only the snapshot it took".
  - (3) `docs/architecture.md` line 1050, the container diagram's alt text, lists "the bundle store, the twin directory and containerlab". `docs/c4/workspace.dsl` line 53 and `structurizr-Containers.svg` draw the snapshot store too, so name it.
  - (4) `scripts/e2e.sh` line 844 says "The dry run touches nothing but the bundle store". The dry run at line 847 also files a snapshot under `snapshots/` (FR-014), so name both stores.

  Check: `shellcheck scripts/bring-up.sh scripts/e2e.sh` is clean, `bash -n scripts/e2e.sh` is clean, `TestE2EScriptExpectsTheRecordsVersion` passes, and `make linkcheck` is clean. per FR-010, FR-014, FR-029 (partial)

- [ ] T081 [pin] Bring the provision input's remaining field comments, one workflow comment and the stage package's two descriptions to 018. Change no code and no message string. T077 moved `ProvisionInput.Branch` and `Scope`; these five sentences still describe the inputs as they were before 018.
  - (1) `internal/provision/workflow_provision.go:57`, inside `case in.BundleID != ""`, says "Already compiled: the read that produced the bundle was the check's". That branch now takes every create a build of this tree starts, with the server's read or the snapshot's stored take (`internal/server/create.go:147–157`, `:222–232`), beside a rebuild's.
  - (2) `internal/provision/types.go:92`, `At`, says "intent: --at verbatim". For `wire.SourceSnapshot` it is the envelope's `at` (`create.go:227`).
  - (3) Lines 94–95 label `BundlePath` and `BundleID` "bundle:", as if `twin provision` alone sets them. Every create sets them too.
  - (4) Lines 97–98, `ObservedAt`, say it is set "with Source intent and BundleID set … a rebuild's provision". Every create sets it, a snapshot's too (`create.go:155`, `:230`).
  - (5) `internal/stage/stage.go:1–3` and `docs/development.md:362` name the stage commands, the provisioning activities and the dry run as `internal/stage`'s callers. The server's create, `stage plan`, `twin step` and `twin rehearse` read and compile through it since 018, and the activities only in a following check's run.

  Check: `make build` and `make lint` are clean, `gofmt -l` is empty, and the diff touches comment lines and that one Markdown line alone. per FR-009, FR-029 (partial)
