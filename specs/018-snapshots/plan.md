# Implementation Plan: Snapshots, the core's one input

**Branch**: `018-snapshots` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/018-snapshots/spec.md`, the brief
([brief.md](brief.md)), the roadmap's [Release 0.3](../../docs/roadmap.md#release-03),
[F-024](../../docs/roadmap.md#f-024) and [F-026](../../docs/roadmap.md#f-026),
[D-010](../../docs/decisions.md#d-010), [D-011](../../docs/decisions.md#d-011),
[D-012](../../docs/decisions.md#d-012), [D-014](../../docs/decisions.md#d-014),
[D-023](../../docs/decisions.md#d-023), [D-026](../../docs/decisions.md#d-026),
[D-040](../../docs/decisions.md#d-040), [D-045](../../docs/decisions.md#d-045),
[D-055](../../docs/decisions.md#d-055), [D-057](../../docs/decisions.md#d-057),
[D-058](../../docs/decisions.md#d-058), [D-060](../../docs/decisions.md#d-060) and
Constitution 2.1.0, amended to 2.2.0 at T003 on 2026-10-27. Research is in [research.md](research.md) (§1 verified at this plan
on the running host, §2 its decisions R-01…R-24, §3 the decision entry D-061 and the
constitution amendment 2.2.0 drafted for the operator, §4 owed at implement), the entities
in [data-model.md](data-model.md), the snapshot's schema, the commands and the formats that
move in [contracts/](contracts/), the validation in [quickstart.md](quickstart.md). No
OpsMill skill was loaded: the feature designs nothing in Infrahub, writes nothing to
`main`, and changes no query, template or check (brief, "Left to the plan"; R-24).

## Summary

Release 0.3's second spec makes the core's one input real. A **snapshot** is one JSON
document of version `1`: an outer part (`snapshot_version`, `snapshot_id`, the take's
`observed_at`) around a body of one CTM `2`, unchanged, and `probes`, a list required and
empty until 016 fills it. Its id is the SHA-256 of the body's canonical bytes with the
inner envelope's `observed_at` left out, by the rule the manifest already uses for the
bundle id (R-01); it is filed as `snapshots/<id>.json` under the state root, beside the
bundles, behind a store of the bundle store's shape that never overwrites (R-04), and the
bundle's CTM sidecar is retired (R-05). The server takes the snapshot for every create:
`twin create --branch` and `--stage` read, take, file, compile, file and start the
provision workflow with the snapshot id and the bundle id, so the workflow begins at the
host check and the worker never reads a branch for a create (R-11); `twin step` and `twin
rehearse` take each stage's snapshot in the plan they already compile (R-13). `twin create
--snapshot <id|file>` builds a twin from a snapshot alone, frozen by rule (R-12, R-08);
`twin compile --snapshot` compiles one and `--ctm` is retired; `intent read --out` writes
one and files it (R-07, R-09). Wherever a record names a bundle id it names the snapshot id
beside it, except in the bundle: `twin.json` moves to `9`, the five documents gain the id,
and their earlier formats are frozen (R-06). The reconcile workflow is untouched, so a
following twin's rebuild records no snapshot until F-026 removes following. Bundle `5`,
the manifest, CTM `2`, the compiler and the three goldens do not move (SC-003).

Verified live at this plan (research §1): two unpinned reads of `fylgja-fixture` 14 s apart
are byte-identical but for `envelope.observed_at`, and a prototype of R-01's encoding
hashes both to one id, `576933ec…`, the candidate for the fixture's snapshot id; the three
fixture CTMs hash the same shuffled or not (`6a8a77fc…`, `91f06cd6…`, `37d7378a…`); the
read compiles to `f764e1fa…` as `CLAUDE.md` records.

Six things the plan found that the spec did not say, each decided here for `analyze` to
settle:

- **Tier 3 asserts the sidecar's presence** (`scripts/e2e.sh` line 595, inside the
  helper every create case runs). No case is added, as SC-006 says, but that assertion
  moves to the snapshot store, and a sidecar's absence cannot be asserted on this host,
  whose `local/bundles/` holds the sidecars of every read since M5: the script asserts
  that no sidecar is newer than the case's start (R-17).
- **A compile refused after a clean read leaves the snapshot filed.** FR-010 says the
  server files nothing for a refused *read*; a snapshot is taken only from a CTM that
  validated, so a compile's refusal (a package the server lacks) keeps an input worth
  keeping. Stated in R-05 and in the records.
- **`--scope` beside `--snapshot` is refused too**, under the same rule as `--branch`,
  `--stage` and `--at` (FR-018 names three): the snapshot carries its scope, as `twin
  compile` takes none because the CTM carries it (R-07).
- **`twin verify`'s block names a bundle id** (`verify.twin.bundle_id`) and is not among
  FR-022's five records; it is left as it is, for F-026 to move with the kind line (R-21).
- **A record of `8` can still step**, and its step's from side then names no snapshot: the
  record's and the step's sides carry `snapshot_id` as an optional string, while the
  record's top level writes an explicit `null` for none (R-06).
- **The provision workflow keeps its read-and-compile branch** for the nine recorded
  histories, which must replay, and for nothing a build of this tree starts; it leaves
  with the reconcile at F-026 (R-10).

## Technical Context

**Language/Version**: Go 1.26.0 (`go.mod`), one static binary, CGO disabled; JSON Schema
2020-12 for the new contract and the six that move; bash for the tier-3 script; Markdown
for the records. No new dependency: SHA-256, `encoding/json` and the existing `jsonschema`
test library.

**Primary Dependencies**: unchanged. Infrahub 1.11.2 is read as before by the same reader;
the Temporal Go SDK v1.49 runs the same five workflows and twenty activities with inputs
that gain one optional field each; containerlab 0.79.0 is untouched. `jq` is used by the
tier-3 script alone, as today.

**Storage**: files only (IX): the bundle store (`bundles/<bundle_id>/`, bundle `5`,
without its sidecar), **the snapshot store** (`snapshots/<snapshot_id>.json`, snapshot
`1`, new), the twin directory (`twin.json` `9`), Temporal history. No database.

**Testing**: tier 1 (`make test`, under 45 s): `internal/snapshot`'s rules over the three
fixture CTMs and their shuffled and `observed-later` forms, the id's independence from
`observed_at` and order and its movement with an artifact byte or a fidelity row, an
independent computation of a stored id, the four refusals, the store's never-overwrite,
the wrapped fixtures compiling to the three goldens, `twin.json` `9` and the frozen `8`,
every moved document against its contract and the frozen copies, the server's `--snapshot`
guards and answers over faked pipelines, the nine histories replaying (quickstart §1);
tier 2 (`make test-contract`): the fixture read twice to one id inside
`TestPinnedReadReproducesItsBundle`, one stage taken twice through the server's path to
one id with the store unchanged, `internal/stages` and `internal/checks` with the id in
their rows (quickstart §7; about a minute more than today); tier 3 (`make test-e2e`): the
nine cases as they are, the sidecar assertion moved, case 1's record line naming the
snapshot, case 5's rebuilt twin reading `snapshot none` (quickstart §8).

**Target Platform**: the development host (Ubuntu 26.04.1), its one Infrahub unchanged, and
CI's `ubuntu-26.04` runner for tiers 1 and 2.

**Project Type**: a feature of the existing single-binary Go project: one new package, the
server's create path, the records and their contracts, a bash tier and Markdown records.

**Performance Goals**: a take is one canonical marshal and one SHA-256 of the CTM's bytes
(6.6 KB for the fixture; research §1.3), negligible beside a read; a create is no slower
than today, since the read and compile move from the worker to the server; tier 1 stays
under 45 s; tier 2 gains one test of about a minute; tier 3 adds no case.

**Constraints**: bundle `5`, the manifest, CTM `2`, the compiler and the three goldens
unchanged (FR-026, SC-003); `observed_at` outside the hashed bytes (VI); no new workflow,
activity, task queue or version marker (VIII), the nine histories replaying; every refusal
the server's (XI); the API at `1`, additive and pre-1.0 as at 014, 015 and 017; nothing on
Infrahub's `main`, no fixture, no query, template or check moves; a session never pushes;
no twin while tier 2 runs; the rebase and re-render limits documented, not tested.

**Scale/Scope**: `internal/snapshot` (the document, the id, the validation, the store;
about 350 lines and as many of tests); the server's take and filing, the create's read and
compile, `--snapshot` on create, `--snapshot` in place of `--ctm` on compile, `intent read`
writing a snapshot, the step's and plan's and rehearsal's rows, the record line and the
kind line (about 400 lines across ten files); the wire, record and workflow inputs (about
120 lines); the findings blocks, the rehearsal's table and the client's flags (about 150
lines); one new contract and six moved, five frozen copies; three wrapped fixtures; the
tier-3 script's helper and five assertions; about fourteen records. The live parts (the
restart, the hand checks, the tiers) are the session's.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 2.2.0 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. One new package in the one binary; SHA-256 and `encoding/json` from the standard library; nothing added, nothing embedded changes. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness and the manufacturer and platform pairs from the PSP | **PASS**. No package, compiler or budget moves; the snapshot names no platform of its own, only the CTM's packages. |
| III | The CTM is the contract; the reader names its model version; approximations and omissions in the envelope's fidelity list, copied by the compiler; nothing read the mapping does not name; the read-only test's list; wiring derived from what was mapped; conformance and completeness checked separately | **PASS**. The reader and its mapping are untouched; the snapshot wraps the CTM it produces, unchanged, and the fidelity list rides in the hashed body (brief, X). The read-only test's lists do not move. |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. The artifacts enter the snapshot as the CTM carries them, verbatim; nothing renders. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **PASS**. The compiler is not touched (`TestCompilerIsPure` stands); `twin compile --snapshot` compiles the snapshot's CTM on `stage.Compile`, the goldens' path, and the three wrapped fixtures compile to the three goldens byte for byte (R-15). The bundle id's rule is reused, not changed. |
| VI | Provenance recorded (branch, `at`, schema hash, scope, mapping and model version in the bundle; `observed_at` in the CTM envelope, the snapshot's outer part and `twin.json`, never in the bundle nor in the bytes a snapshot's id hashes); `at` passed verbatim or not at all; where the source cannot replay time, the snapshot's id addresses intent | **PASS**. Under 2.1.0 on its own: `observed_at` is in the snapshot's outer part and the twin directory, never the bundle. 2.2.0 adds the snapshot to the provenance sentence and the F-025 sentence, which binds nothing here (R-01, R-02). |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | **PASS**. The host check is where it was, first in every provision; nothing is named per twin. |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **PASS**. No workflow, activity, budget, marker or queue is added or removed; `ProvisionInput`, `RecordInput`, `StepSide` and `RehearseStage` gain `snapshot_id`, omitted when empty, so the nine recorded histories replay; the provision workflow takes a compiled input as the rebuild's already does and branches on the input's shape, not on a new marker (R-10); the Compile activity stops writing a sidecar and nothing else; ids and paths cross, never a snapshot's bytes. |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. The snapshot store is a second directory of files behind an interface of the bundle store's shape, small enough for object storage to replace at M8 (R-04); `twin.json` `9` names the snapshot; nothing else holds state. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. The manifest is untouched; five identifiers are added, each with its severity, exit, step and object (R-03, R-07); a snapshot holds configuration, so it lives in the store and crosses as a file, never in a finding, a log line or a document (as the CTM does today); no credential reaches any output. |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | **PASS**. `snapshot` is an argument of `twin.create` and `twin.compile`, a snapshot file crosses in the request's `files` as the CTM does today, and `intent.read` answers with the versioned snapshot document; every guard and refusal is the server's but the client's own refusal of a file it cannot read, as for a CTM today; the tier-2 test calls the server's handler as test code may; `TestClientReachesTheCoreThroughTheAPIAlone` is unchanged. |

**Development Workflow gates**: three tiers (tier 2 against the real Infrahub; tier 3
never in CI) **PASS**; verification just-in-time and recorded (research §1: the host's
state, the two reads, the prototype's ids, the compile, tier 3's assertions, the schemas'
strictness; §4 what is owed at implement) **PASS**; documents (three glossary terms, D-061
and 2.2.0 drafted, the architecture and the glossary grepped for the sidecar at the close,
the C4 model redrawn in the same change) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the mapping, one per source, documented (D-057).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **None flagged.** A second file store is D-014's own shape, not a database; the
snapshot is the compiler's input wrapped, not a binding stage between a bundle and a twin.

**Post-design re-check (after Phase 1)**: unchanged. The design adds one package, one
store, one contract, five identifiers and one record version, and violates no gate. The
six departures from or refinements of the spec's text listed in the Summary are the
plan's to flag and `analyze`'s to settle; beside them, D-061 and Constitution 2.2.0 are
`[operator]` tasks at `analyze`, before the records move, and the roadmap's uncommitted
F-024 and F-026 edits (research §1.9) are the operator's to commit.

## Project Structure

### Documentation (this feature)

```text
specs/018-snapshots/
├── brief.md                 # the specify brief (committed)
├── spec.md                  # the specification
├── plan.md                  # this file
├── research.md              # §1 verified at plan (the host, two reads, the prototype's ids, the compile, tier 3, the schemas), §2 R-01…R-24, §3 D-061 and Constitution 2.2.0 drafted, §4 owed
├── data-model.md            # Phase 1: the snapshot, its id, the store, the records and documents, the workflow inputs, the identifiers, the client and the API, the fixtures, tier 3, the documents
├── quickstart.md            # Phase 1: §0 the operator's, §1 tier 1, §2–§6 by hand, §7 tier 2, §8 tier 3, §9 records
├── contracts/
│   ├── snapshot.schema.json    # snapshot 1, to land as contracts/snapshot.schema.json
│   ├── snapshot-commands.md    # cli.md's and api.md's "018: snapshots" sections: the commands, the guards, the text, the identifiers
│   └── formats.md              # twin.json 9, the findings blocks that gain the id, show, stages, step, rehearsal, api.schema.json, the frozen copies, the markdown table
├── checklists/requirements.md
└── tasks.md                 # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
internal/snapshot/                     # NEW: the document (Snapshot, Version "1"), Take, the hashed body and the id (ID, IsID), Marshal/Unmarshal and the refusals (VersionError, InvalidError, IDMismatchError), Store/DirStore (Put, Has, Path, Fetch; ErrIDMismatch); snapshot_test.go, id_test.go, store_test.go
contracts/
├── snapshot.schema.json               # NEW: version 1, $id …/contracts/snapshot/v1
├── twin.schema.json                   # 9: snapshot_id, source snapshot, step sides
├── findings.schema.json               # snapshot_id top-level; dry_run.follow.reason snapshot
├── show.schema.json, stages.schema.json, step.schema.json, rehearsal.schema.json   # the id in record, plan_stage, side, stage
├── api.schema.json, api.md, cli.md    # snapshot on twin.create and twin.compile; files on twin.create; the 018 sections
testdata/snapshot/                     # NEW: three-node.json, lossy.json, mixed.json, the fixture CTMs wrapped
internal/ctm/                          # unchanged (CTM 2)
internal/bundle/store.go               # Store loses PutCTM; DirStore the sidecar
internal/compiler/                     # unchanged (bundle 5, goldens)
internal/stage/stage.go                # unchanged; reproducibility_contract_test.go gains the snapshot id assertions
internal/stages/plan.go                # Pipeline.Take between Read and Compile; PlanStage.SnapshotID; File without the CTM
internal/stages/blocks.go              # PlanStage.Block carries snapshot_id
internal/findings/
├── finding.go                         # snapshot.invalid, snapshot.version.unsupported, snapshot.id.mismatch, snapshot.unknown, snapshot.flags.conflict
├── render.go                          # Document.SnapshotID; DryRunFollow reason snapshot; PlanStage, RehearsalStage, ShowRecord, StepSideBlock gain the id; show's source
└── testdata/contracts/017-dcim-reader/   # NEW: the frozen stages, step, rehearsal, show and findings schemas as 017 left them (R-06)
internal/lab/
├── twin.go                            # TwinVersion "9"; RecordFields.SnapshotID; NewRecord's rules by source; NewStepRecord carries the sides' ids
├── wire/types.go                      # SourceSnapshot; RecordInput.SnapshotID; StepSide.SnapshotID; TwinRecord.SnapshotID
├── env.go                             # Paths.Snapshots
└── testdata/contracts/017-dcim-reader/twin.schema.json   # NEW: the frozen 8
internal/provision/
├── types.go                           # ProvisionInput.SnapshotID; RehearseStage.SnapshotID
├── workflow_provision.go              # the record input carries the id; the read-and-compile branch kept for the histories
├── activities.go                      # Compile no longer files a sidecar
└── workflow_step.go, workflow_rehearse.go   # the sides' ids ride through unchanged code
internal/rehearsal/
├── report.go                          # Stage.SnapshotID into the block
└── markdown.go                        # the table's snapshot column before bundle
internal/server/
├── snapshot.go                        # NEW: takeSnapshot, the store, the snapshot lines, the --snapshot guards, resolveSnapshot (id or file)
├── create.go                          # the read, take, compile and filing before the run; --snapshot; the follow guard's new sentence
├── dryrun.go                          # snapshot_id … stored: line; follow reason snapshot
├── filing.go                          # fileCompiled without the CTM; keepCTM removed
├── read.go                            # writes and files a snapshot; snapshot.json in the files frame; the summary's snapshot clause
├── compile.go                         # --snapshot in place of --ctm; the snapshot's refusals; snapshot_id in the document
├── step.go, rehearse.go, stages.go    # the sides' ids, the rows' ids, the plan's lines
├── show.go                            # the record line's snapshot clause; the kind line's note; source snapshot never follows
└── handlers.go                        # twin.create's snapshot and one file; twin.compile's snapshot
internal/cli/
├── create.go                          # --snapshot <id|file>; the file read and sent
├── compile.go, files.go               # --snapshot <file>; readSnapshot in place of readCTM; writeSnapshot
└── read.go                            # --out writes a snapshot
cmd/fylgja/serve.go, worker.go         # the state root line names snapshots/
scripts/e2e.sh                         # compiled_id with --snapshot; the sidecar assertion moved; the record line's snapshot; case 5's null
docs/architecture.md (§2, §3, §4.2–§4.6), docs/c4/workspace.dsl (+ make diagrams), docs/glossary.md, docs/development.md,
docs/verified-facts.md, docs/roadmap.md, docs/decisions.md (the operator's D-061), README.md, CLAUDE.md,
.specify/memory/constitution.md and .specify/templates/plan-template.md (the operator's 2.2.0)
```

**Structure Decision**: the snapshot is a package of its own, `internal/snapshot`, beside
`internal/ctm` and `internal/bundle`: it imports the CTM (whose canonical form it reuses)
and nothing of the server, the compiler or the reader, so the core's input is one small
package the production shape's split can lift whole. Its store mirrors the bundle store
file for file (`Put`, `Has`, `Path`, `Fetch`, the same atomic write and the same
never-overwrite rule), two interfaces of one shape rather than one generic interface,
because their currencies differ (a directory of files; one document). Where the server
takes a snapshot is one file, `internal/server/snapshot.go`, called by the create, the dry
run, the read and the stages' pipeline, so the take and the filing are worded once; the
stages' `Pipeline` gains a `Take` step between `Read` and `Compile`, which is how the
plan, the step and the rehearsal all take one by construction. The component changes are
drawn in `docs/c4/workspace.dsl` (the server's `snapshot` component and the snapshot store
container; the worker's workflows no longer reading for a create) and `make diagrams`
redraws the views.

## Order of the work

0. **The operator's, before the records move**: D-061 appended and Constitution 2.2.0
   ratified at `analyze`, the plan template's Constitution Check moved to 2.2.0 (research
   §3); the roadmap's F-024 and F-026 edits committed (research §1.9).
1. **The snapshot and its store** (tier 1 alone): `internal/snapshot` with its rules, the
   contract, the three wrapped fixtures and the golden test, the five identifiers, the
   bundle store without `PutCTM`. Checkpoint: `make test` and `make lint` green.
2. **The records and the wire**: `twin.json` `9` and `NewRecord`'s rules, the wire types,
   the workflow inputs, the record activities, the findings blocks and the moved contracts
   with their frozen copies, the rehearsal's table. Checkpoint: `make test`, the nine
   histories replaying.
3. **The server and the client**: the take and filing; the create's read and compile; the
   dry run's line; `--snapshot` on create with its guards and answers; `--snapshot` on
   compile; `intent read` writing and filing; the plan's, step's and rehearsal's ids; the
   record and kind lines; the client's flags and files; the API's arguments. Checkpoint:
   `make test`, `make lint`, the harness over every refusal before any connection.
4. **Tier 3's script and the documents**: `scripts/e2e.sh`; the contracts' prose; the
   architecture, the glossary, the development notes, the C4 model, the README, `CLAUDE.md`.
5. **The host, live** (quickstart §0 and §2–§6): the worker and the server restarted and
   verified, the hand checks, the fixture's snapshot id read. The session's.
6. **Tier 2** (quickstart §7), then **tier 3** whole and narrowed (quickstart §8). Live;
   the session's.
7. **The records at the close** (R-18): the architecture grepped for the sidecar and the
   provision's read; `docs/verified-facts.md` (research §1); the roadmap (F-024 built);
   `CLAUDE.md`'s Formats and State with the fixture's snapshot id; D-061 and 2.2.0 by the
   operator.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None.
