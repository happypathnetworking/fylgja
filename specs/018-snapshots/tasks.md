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

- [ ] T047 [US6] `scripts/e2e.sh` (R-17; snapshot-commands.md "Tier 3"). Make these changes:
  - `compiled_id` (lines 522–531) reads with `intent read --out "$OUT/snapshot-$case.json"` and compiles with `twin compile --snapshot`. Rename its files from `ctm-` to `snapshot-`.
  - `create_twin` (from line 560) reads `SID` from the create's `.snapshot_id` and asserts `snapshots/$SID.json` exists. Its line 595 sidecar check becomes "no `bundles/*.ctm.json` newer than the case's start": take a marker file at the case's start and use `find "$FYLGJA_STATE_ROOT/bundles" -maxdepth 1 -name '*.ctm.json' -newer "$marker"`, which must be empty. It expects `twin.json`'s `.snapshot_id==env.SID`.
  - Case 1's `twin show` grep (near line 871) gains `snapshot $SID1, bundle_id $BID1`.
  - Case 5's rebuilt twin expects `.show.record.snapshot_id==null`.
  - Case 7's steps expect `.step.to.snapshot_id` to be a string.
  - The destroy comment near line 1197 still names `.reads/` as the reconcile's.

  No case is added, and `PLATFORMS=nokia_srlinux` still ends `E2E-PARTIAL`. Run `shellcheck scripts/bring-up.sh scripts/e2e.sh` clean. Check each changed `jq` filter offline against documents the tier-1 tests produce or against `local/e2e-*.outputs`, as the memory note on offline checks says: an old output must fail the new filter for the reason expected, and a hand-edited one must pass. Note the checks in this task.

- [ ] T048 [P] [US6] `contracts/cli.md` and `contracts/api.md`: append `## 018: snapshots` to each, after the 017 section. Use the text of [contracts/snapshot-commands.md](contracts/snapshot-commands.md)'s two sections, with relative links fixed for their new home: `snapshot.schema.json`, `formats.md`'s content, `../docs/decisions.md#d-061`. Fold `formats.md`'s per-schema changes into cli.md's "Formats and versions" table, as earlier sections do. In the earlier sections, mark `twin compile --ctm` and the sidecar retired, where they are described as current, with a one-line pointer to 018, as 017 marked what it retired. Run `make linkcheck` clean.

- [ ] T049 [P] [US6] Check that the six moved schemas' and the new one's descriptions quote formats.md's 018 sentences exactly, and that `contracts/README.md` (if present) or the contracts index lists `snapshot.schema.json` with its version. Grep `contracts/` for `ctm.json`, `--ctm` and `sidecar`. Each hit is either historical, inside an earlier section, or made true.

**Checkpoint**: `make test`, `make lint`, `shellcheck`, `make linkcheck`.

---

## Phase 12: User Story 6, part 3 — the host, live (Priority: P3)

**Goal**: the feature proved on the development host: the processes from this tree, the
hand checks of quickstart §2–§6, then the whole contract tier, then the end-to-end tier
whole and narrowed (SC-001–SC-006).

**Independent Test**: quickstart §2–§8's expected outcomes, each recorded in its task's
note.

- [ ] T050 [live] Restart the worker and the server from this tree's `bin/fylgja` (`make build` first), as `CLAUDE.md` prescribes, and verify both:
  - `/proc/<pid>/exe` is not `(deleted)`;
  - the environments carry `INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT`, `FYLGJA_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`;
  - the server's report names `snapshots:` in its state root line (T008), both listeners, the plaintext warning, the default scope and both packages;
  - the worker's start-up report names `snapshots:`;
  - from inside each Infrahub task worker, `POST /v1/twin/show` answers `200` with the token and `401` without (`specs/015-proposed-change-rehearsal/quickstart.md` §2).

  Restart the dev server if it is down. Record the pids and lines, never a token.

- [ ] T051 [live] [US1] [US3] [US4] The hand checks of quickstart §2 to §5, on a host with no twin (`twin show` → `none`), recording each outcome in this task's note:
  - **§2**: the wrapped fixtures compile to the goldens; `--ctm` is unknown, and the server's log shows no request; a hand-wrapped CTM compiles; `local/snapshots` count unchanged.
  - **§3**: two `intent read --out` of `fylgja-fixture` give one id, **the fixture's snapshot id for T062** (`576933ec…` is the candidate). Their diff is the two `observed_at` lines. The store holds the first take byte for byte. The `jq` recipe reproduces the id.
  - **§4**: the dry run's two `stored:` lines; the create `ok` with `f764e1fa…`. The run's activities read from `temporal workflow show` are `CheckHost, StageBundle, DeployLab, AwaitReadiness, PushConfig, RecordTwin, StopFollowing`, with no `ReadIntent` or `Compile` (SC-001). `twin show`'s record line; `twin.json` `9`; no sidecar newer than the create; a refused read (`--scope tag:nothing`) starting no run and filing nothing.
  - **§5**: the three refusals; the create from the id with no Infrahub request in the server's log; the kind `frozen; not following; built from snapshot …`; no `fylgja-follow` Schedule; `step.twin.unsteppable`; the file with no id; the file with a wrong id; a pinned read's snapshot showing `pinned at <T>; not following; built from snapshot …`.

  Destroy every twin at the end. Defects found get a tier-1 test pinning them, fixed in the package that holds the behaviour.

- [ ] T052 [live] [US5] The hand checks of quickstart §6 on `B=fylgja-test-018`, recording each outcome in this task's note:
  - the throwaway branch, its proposed change and two stages, by the fixture tool;
  - `stage plan` twice, giving equal snapshot ids and the branch point `null`;
  - `twin create --stage $B/seeded`, then `twin step --stage $B/third-link --allow-restart`, whose document and `twin.json` name both sides' snapshots;
  - `twin destroy`;
  - `twin rehearse --branch $B --markdown`, whose header carries the `snapshot` column, within 4,092 bytes;
  - `-delete`.

  Afterwards `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange` and `FylgjaStage` count 0.

- [ ] T053 [live] The whole contract tier (quickstart §7). Preconditions: no twin on the host, and the worker and the server from this tree beside the bridge (T050). Run `set -a; . local/.env; set +a; make test-contract 2>&1 | tee local/018-contract.out`, started detached with its exit status in a file and waited on in foreground calls of under ten minutes. Expected green, about a minute over 017's 1,714.7 s. In the output: `TestPinnedReadReproducesItsBundle` and `TestStageTakenTwiceHasOneSnapshot` log their ids; `internal/stages` and `internal/checks` are green, `TestChecksInsideInfrahub` included, with the id in their rows (SC-006). Afterwards, Infrahub as the contract tier leaves it (`CLAUDE.md`, "Stages"). Record the total time, `internal/stages`' and `internal/checks`' times, and the ids. Never boot a twin while it runs.

- [ ] T054 [live] The end-to-end tier, on a quiet host after T053, never beside it (quickstart §8). Preconditions:
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

**Checkpoint**: every tier green; the fixture's snapshot id known; the host left with no
twin and Infrahub as the contract tier leaves it.

---

## Phase 13: Polish — the records at the close

**Purpose**: every document says what is now true (FR-028, FR-029; R-18, R-23; quickstart §9).

- [ ] T055 [P] `docs/architecture.md`, per R-18:
  - §2: the pipeline names the snapshot.
  - §3: a Snapshot row in the core objects' table.
  - §4.2: the CTM is the snapshot's body.
  - §4.3: the compiler's input is a snapshot's CTM.
  - §4.4: a create's provision begins at the host check; the sequence drawing; `ReadIntent` and `Compile` are the reconcile's alone.
  - §4.5: the state root tree gains `snapshots/` and loses the sidecar and its paragraph.
  - §4.6: the commands.

  Work through T002's grep hits and grep again (`ctm.json`, `sidecar`, `.reads`, `ReadIntent`, `--ctm`, `read and compile`). Every sentence is made true or marked historical. State the rebase and re-render limits once, linking D-061.

- [ ] T056 [P] `docs/glossary.md`:
  - new entries: Snapshot, Snapshot id (with the hashed-bytes sentence and the two limits), and Snapshot store;
  - Bundle store without the sidecar;
  - Frozen twin and Pinned gain the snapshot twin;
  - Intent reference names the snapshot as a reference;
  - grep for `ctm.json`, `--ctm` and `sidecar`.

- [ ] T057 [P] `docs/development.md`: the state root listing gains `snapshots/`, and the frozen copies' paragraph names `017-dcim-reader/`'s sixteen copies and the count `49`. Note the snapshot's tier-1 tests where the tiers are described. Grep for `--ctm` and `ctm.json`.

- [ ] T058 [P] `README.md`:
  - the offline walk-through compiles `testdata/snapshot/mixed.json` with `twin compile --snapshot` to `ecb665f5…` (R-15);
  - the `intent read --out` lines say a snapshot;
  - the stage commands' sample lines gain `snapshot_id`;
  - the rehearsal table sample (line 569) gains the `snapshot` column.

  Run every command shown that needs only the server against this tree, and paste its real output.

- [ ] T059 [P] `docs/verified-facts.md`: under 2026-10-27, research §1.2 (two unpinned reads differ in `observed_at` alone) and §1.3 (the hashed-bytes encoding and the `jq` recipe agree), with T051's fixture id and T046's stage-taken-twice result, each with Infrahub 1.11.2 and the date.

- [ ] T060 [P] `docs/roadmap.md`: F-024 marked built by 018, with a one-line summary and links to D-061 and this feature; Release 0.3's list moves its marker to F-026 next. The brief (`specs/018-snapshots/brief.md`) is left as written.

- [ ] T061 [P] Re-read `SECURITY.md` and `.env.example` for anything the snapshot changes. Expected: nothing in `.env.example`. A sentence in `SECURITY.md` that a snapshot holds configuration, as the CTM does, if it describes the CTM's or the bundle store's contents. Grep the tree for any log or finding message that could carry a snapshot's bytes (`grep -rn 'snapshot' internal/server/*.go | grep -i 'log\|Printf'`). Only ids and paths may cross.

- [ ] T062 `CLAUDE.md`:
  - Formats: snapshot `1`; `twin.json` `9`; `--ctm` retired; the fixture's snapshot id from T051 beside `f764e1fa…`.
  - The Environment's description of the server's report: `snapshots:` in the state root line.
  - Build and test: tier 2's and tier 3's new times from T053 and T054, and the tier-1 time if it moved.
  - The fixture branch's paragraph: "It compiles to `f764e1fa…` … and its snapshot id is `<id>`".
  - State: 018 closed, summarised as 017's entry is (D-061, Constitution 2.2.0, the snapshot store, `twin.json` `9`, the sidecar retired, the tiers' results); **Next**: F-026.
  - The constitution's version where `CLAUDE.md` names it (2.2.0).

- [ ] T063 The closing gates and greps:
  - `make build`, static; `make test` uncached under 45 s; `make lint`; `go vet -tags contract,fixture,e2e ./...`; `shellcheck scripts/bring-up.sh scripts/e2e.sh`; `make linkcheck`;
  - `git diff --stat main -- testdata/golden` empty;
  - `/usr/bin/grep -rn -- '--ctm\|PutCTM\|\.ctm\.json\|sidecar' --include=*.go --include=*.md --include=*.sh --include=*.json --include=*.dsl .`, excluding `specs/0[01]*`, `local/` and `.venv/`. Each hit is historical, the reconcile's `.reads/`, or a retirement note;
  - the credential greps over the tree and the branch's history (`/usr/bin/grep`, since Bash's `grep` skips git-ignored files), finding nothing;
  - `TestFrozenContractCopiesAgree` at 49.

  Record each result in this task's note.

- [ ] T064 [operator] The operator's review of the feature, the commits by hand that the runs left uncommitted, and `make command-log` once the session is closed. Record the review's outcome in this task's note.

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
