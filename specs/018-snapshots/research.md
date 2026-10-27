# Research: Snapshots, the core's one input

**Feature**: `018-snapshots` · **Plan**: [plan.md](plan.md) · **Date**: 2026-10-27

§1 is what was verified on the running system at this plan, §2 the decisions the brief
left to the plan (R-01…R-24), §3 the decision entry and the constitution amendment drafted
for the operator, §4 what is owed at implement. Every claim below about how Infrahub, the
server or the tree behaves was read or run on 2026-10-27 unless it says otherwise; a
claim about the stage-twice case is tier 2's to prove, not this plan's.

## 1. Verified at this plan

The development host, Infrahub 1.11.2, `main` at `7c413536…`, the fixture branch
`fylgja-fixture` as 017 re-seeded it, the tree at `168fd63` plus the roadmap's uncommitted
edits.

### 1.1 The host's state

- No twin: `twin show` answered `twin: none: no lab fylgja, no twin directory`, `kind:
  none`, `in flight: none`.
- The server and the worker ran on a binary that read `(deleted)` in `/proc/<pid>/exe`
  (built 00:18, started earlier). Both were stopped and started again from `bin/fylgja`
  as `CLAUDE.md` prescribes and verified: `exe` not deleted, the environment carrying
  `INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT`, `FYLGJA_API_TOKEN` and
  `FYLGJA_DEFAULT_SCOPE`; the server's report `listening on 127.0.0.1:7650 (API version
  1, build 0.1.0-dev)`, `listening on 172.17.0.1:7650 (…)`, the plaintext warning, the
  state root, `default scope: tag:fylgja`, both packages with their logins set; the
  worker's `Started Worker … TaskQueue=fylgja`.
- No converge loop runs (`pgrep -af converge-loop` matched nothing but the shell asking);
  `local/converge-loop.lock` is a leftover of 017's attended loop.
- `local/bundles/` holds every bundle since M5 with its sidecar `<bundle_id>.ctm.json`
  beside it, and `local/bundles/.reads/` two run-named CTMs a cancelled check left: what
  FR-008's "sidecars already on disk are never read" is about, and why tier 3 cannot
  assert a sidecar's absence on this host (R-17).

### 1.2 Two reads of the fixture differ in `observed_at` alone

`bin/fylgja intent read --branch fylgja-fixture --out <file>` twice, 14.4 s apart, through
the restarted server:

| | `observed_at` | summary line | SHA-256 of the CTM file |
|---|---|---|---|
| read 1 | `2026-10-27T14:13:38.380155Z` | `3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports (branch fylgja-fixture, scope tag:fylgja, schema 7c413536d67ef86321c629c076a0d3a4)` | `69b4314c…` |
| read 2 | `2026-10-27T14:13:52.736118Z` | the same | `9fe1bb08…` |

`diff` of the two files is one line, line 5, the envelope's `observed_at`. So Infrahub
serves the same artifact bytes to two unpinned reads and the reader's output is
canonical (`ctm.Normalize`), which is the premise of SC-002's first half: the same intent
read twice gives one snapshot id once `observed_at` is out of the hashed bytes.

### 1.3 A prototype of R-01's id agrees on both reads and on every fixture

A throwaway `go run` program under `local/` (git-ignored, removed after the run; not the implementation) encoded
the hashed body as R-01 defines it — `{"ctm": <the CTM normalised, its envelope without
observed_at>, "probes": []}`, `json.MarshalIndent` with two spaces, a trailing newline —
and hashed it with SHA-256:

| Input | Candidate id | Hashed bytes |
|---|---|---|
| read 1 and read 2 of `fylgja-fixture` | `576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482` | 6,557 |
| `testdata/ctm/three-node.json`, `observed-later.json` (its `observed_at` six days later), `three-node.shuffled.json` (its lists reordered) | `6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6` | 6,568 |
| `lossy.json`, `lossy.shuffled.json` | `91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c` | 6,134 |
| `mixed.json`, `mixed.shuffled.json` | `37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf` | 5,761 |

The hand recipe `jq --indent 2 '{ctm: del(.envelope.observed_at), probes: []}' <ctm> |
sha256sum` gave the same three ids (`576933ec…`, `6a8a77fc…`, `37d7378a…`): `jq` keeps
the file's key order, indents as Go does, writes `[]` for an empty list and ends with a
newline, and none of the fixture artifacts holds `<`, `>` or `&`, the characters Go's
encoder writes as `<`, `>` and `&`. The implementation's tests re-derive
every id; `CLAUDE.md` records the fixture's as implement computes it with the shipped
code, which equals `576933ec…` if R-01 is built as written.

### 1.4 The read compiles to the fixture's bundle

`twin compile --ctm` of read 1 answered `ok`, `bundle_id
f764e1fabdcd70b39a91cc2269ef0a3443c7ae6752af62bdf0936c4eda034147`, the id `CLAUDE.md`
records for the live fixture; the three goldens hash to `43d91715…`, `4213b3cf…` and
`ecb665f5…` by the `sha256sum` recipe. The compiler is not touched, so SC-003 holds by
construction once the wrapped fixtures compile through the same function (R-15).

### 1.5 Where the pieces are in the tree

Read, not run:

- `internal/server/filing.go`: `fileCompiled` files the bundle and the CTM beside it
  through `bundle.Store.PutCTM`; `internal/provision/activities.go`'s `Compile` does the
  same inside a run. Those are the sidecar's two writers (FR-008). `bundles/.reads/` is
  written by `ReadIntent` and discarded by `Compile`, both the reconcile's (FR-013).
- `internal/server/create.go`: `runCreate` resolves a stage on the server and starts the
  provision workflow with `Source: intent, Branch, At, Scope, Stage, Follow`; the dry run
  (`runCreateDryRun`) already reads, compiles and files in the server's process on
  `stage.Read` and `stage.Compile`, bounded by `stage.ReadTimeout` (5 min, M1's read
  bound). The create's live path is the dry run's path plus the start (R-11).
- `internal/provision/workflow_provision.go`: `Provision` branches on the input's shape:
  `Source: bundle`, or `BundleID` set (the rebuild's already-compiled input, which
  records the check's `ObservedAt`), else `readAndCompile`. A server-compiled create is
  the second shape with a snapshot id beside it (R-10).
- `internal/stages/plan.go`: `Pipeline{Read, Compile, File}`; `build` runs read, compile,
  file in that order; `PlanStage` carries `Bundle`, `ObservedAt` and `Findings`; the
  step (`internal/server/step.go`) and the rehearsal (`rehearse.go`) build every stage
  through it (R-13).
- `internal/lab/twin.go`: `TwinVersion "8"`; `NewRecord` refuses by `Source`;
  `NewStepRecord` moves the top level to the target; `internal/lab/wire/types.go`:
  `StepSide{Stage, BundleID, At, Branch}` is one type for the step's input, the record's
  sides and the record step's input (R-06).
- `internal/rehearsal/markdown.go`: the table's header is `| stage | at | bundle | step |
  wait | verify | new verification failures | verdict |`; `fit` shrinks to `| stage |
  verdict |` when the markdown would exceed `CommentMax` (4,092 bytes) (R-14).
- `internal/findings/frozen_contracts_test.go`: `frozenContractCopies = 33`, and every
  copy of one `<feature>/<name>` must be byte-equal across packages. `internal/lab`'s
  copies are named by the feature that wrote the frozen version (`009-stepping` holds
  `twin` 4, `010-verify` 5, `014-…` 6, `015-…` 7); `internal/ctm`'s and `internal/bundle`'s
  one copy each sit under `017-dcim-reader`, the feature that froze them (R-06).
- The contracts are strict: `findings.schema.json`'s top level, `show.record`, `twin`,
  `plan_stage`, `dry_run` and `dry_run.follow` are `additionalProperties: false`, and
  `dry_run.follow.reason` is an enum of four. Each new key is a schema change with a
  frozen copy of the old file (R-06); `show.record.source` is the enum `intent | bundle`
  (R-08).
- `scripts/e2e.sh`: `compiled_id` reads with `--out` and compiles with `--ctm` (lines
  522–531); `create_twin` asserts the sidecar's presence (595); `FYLGJA_STATE_ROOT` is
  `local/` (139); case 1 greps `twin show`'s text for the 017 clause (871); case 5
  asserts `show.record.bundle_id` and the check's ids; the destroy comment at 1197 names
  `.reads/` (R-17).
- `contracts/cli.md` and `api.md` end with a section per feature (`## 017: the scope and
  the DCIM reader`), each with the commands, the text, the identifiers, the formats and
  versions, the workflows and tier 3; the 018 sections follow the shape
  ([contracts/snapshot-commands.md](contracts/snapshot-commands.md)).
- `docs/decisions.md` ends at D-060, so D-061 is free; the constitution is 2.1.0 and the
  plan template's Constitution Check names it (R-19).
- `cmd/fylgja-fixture`'s flags: `-propose`, `-stage <label> [-at] [-description]`,
  `-add-link`, `-add-interface`, `-generate`, `-close`, `-delete`, as 015's quickstart
  composes a proposed change with stages (quickstart §6).

### 1.6 Not verified here, and why

- **The same stage taken twice gives one id.** It follows from §1.2 (a pinned read is a
  read; D-012, D-045) and tier 2 proves it through the server's path (R-16); composing a
  proposed change for a hand check at plan time would leave Infrahub holding one.
- **A rebase moves a stage's snapshot** and **an artifact re-rendered to different bytes
  moves it**: documented limits, tested by nothing (brief; `docs/verified-facts.md` 10-16
  already records the rebase's re-stamping).
- **The workflow service's replay** of the nine histories with the inputs' new optional
  fields: tier 1's `workflow_replay_test.go`, at implement.

### 1.7 The roadmap's edits are uncommitted

`git status` shows `docs/roadmap.md` modified (F-024 reworded for the wrap and the
retired sidecar; F-026 added; the release's list and the table) and `specs/018-snapshots/`
untracked. Both are the brief's "owed before the work starts", done on 2026-10-27 and not
yet committed; the operator commits them (plan, Order of the work, 0).

## 2. Decisions

Each is Decision, Rationale, Alternatives considered. Names in code are the plan's and
`tasks` may rename them; the identifiers, the JSON keys, the file names and the text are
the contract's ([contracts/](contracts/)).

### R-01 The id: SHA-256 over the canonical bytes of the body without `observed_at`

**Decision.** `snapshot_id` is the lowercase-hex SHA-256 (64 characters, eight shown with
an ellipsis in text) of the **hashed bytes**: the JSON document `{"ctm": …, "probes":
[]}` in which `ctm` is the CTM after `ctm.Normalize` with its envelope's `observed_at`
left out (no key), encoded as `ctm.Marshal` encodes a CTM — the struct's field order,
two-space indent, LF, a trailing newline, Go's default escaping. `probes` is `[]` in
version 1. The hashed bytes are never stored: the stored document carries the outer part
and the inner `observed_at` beside the same body. Implemented in `internal/snapshot` by a
`hashed` envelope type that lists `ctm.Envelope`'s fields but `ObservedAt`, in its order
and with its tags, held to the envelope by a reflection test, so a field added to the
envelope fails tier 1 until the hashed form names it or leaves it out on purpose. The
hand recipe is `jq --indent 2 'del(.snapshot_version, .snapshot_id, .observed_at,
.ctm.envelope.observed_at)' snapshots/<id>.json | sha256sum`, exact for a document whose
strings hold none of `<`, `>` and `&` (§1.3); the schema says so in one sentence.

**Rationale.** The brief fixes the algorithm as the bundle's unless a reason to differ
appears, and none did: SHA-256 and 64 hex characters let `IsID` be one function and the
client tell an id from a file by its shape (R-07). Reusing the CTM's canonical encoding
keeps one convention for one document; the CTM's own stored bytes are what the body
carries. Leaving the key out, rather than writing it empty, is what "removed" means and
what the recipe reproduces.

**Alternatives.** A compact, key-sorted encoding (RFC 8785): a second canonical form of
one document beside the CTM's, and still Go's escaping. Writing `observed_at` empty in the
hashed bytes: simpler to implement, but the spec says removed, and a reader of the recipe
would have to know the exception. Hashing the stored bytes with the one line cut by text:
fragile against any reformatting.

### R-02 The outer part: version, id, and the take's `observed_at` equal to the CTM's

**Decision.** `snapshot_version` is `"1"`. `snapshot_id` is R-01's. `observed_at` is the
take's, UTC with six fractional digits (`stage.ObservedAtFormat`), and in version 1 it is
the inner CTM's `observed_at`, copied: one take is one read. In a document Fylgja writes
(the store's, `intent read --out`'s) all three are present. In a file a client sends
(`twin create --snapshot <file>`, `twin compile --snapshot <file>`), `snapshot_id` is
optional, computed when absent and checked when present (`snapshot.id.mismatch`), and
`observed_at` is optional, filled from the inner CTM when absent and refused
`snapshot.invalid` when present and either not of the CTM's form or not equal to the
inner CTM's. Neither is hashed.

**Rationale.** A hand user wraps a bare CTM in `{"snapshot_version": "1", "ctm": …,
"probes": []}` and nothing else (brief; FR-005). An outer time lets a reader of the store
list takes without parsing a CTM, and gives 016 and F-025 a field to let differ, with a
version bump, when a take is more than one read. Holding the two equal now says what a
take is in version 1 and refuses a file that claims otherwise.

**Alternatives.** No outer `observed_at`: the brief's table and FR-001 name it. Letting
the two differ now: a difference would mean nothing yet.

### R-03 Validation, in order, and the rules

**Decision.** `snapshot.Unmarshal` reads a file strictly (unknown keys refused, as the
CTM's are). In order: (1) `snapshot_version` first, on its own: not `"1"`, or absent, is
`snapshot.version.unsupported`, naming the version read (or none) and `"1"`; (2) the outer
shape: not an object, an unknown key, `ctm` absent, null or not an object, `probes`
absent, null, not a list or not empty, `snapshot_id` present and not 64 lowercase hex
characters, `observed_at` present and not of the CTM's form or not the inner's — each
`snapshot.invalid`, naming the field (`probes`, `snapshot_id`, `observed_at`, `ctm`); (3)
the inner CTM under `ctm.Unmarshal`'s own refusals, each object prefixed `ctm.`:
`ctm.version.unsupported` on the file given, `data.required.missing` naming
`ctm.envelope.fidelity`, `ctm.links` or `ctm.devices[<i>].interfaces`; (4) the id
computed and, when declared, compared: `snapshot.id.mismatch` naming both; (5) at
compile, `validate.Validate`'s rules on the CTM as `twin compile` applies them today. An
id the store does not hold is `snapshot.unknown`, naming the id and the store's directory.
Exits and steps: on `twin compile`, as the CTM's rules there, rejection, exit 1, no step;
on `twin create --snapshot`, rejection, exit 1, at `resolve`; `snapshot.flags.conflict`
(R-07) is exit 2 at `start`, as `stage.flags.conflict` is.

**Rationale.** FR-003 mirrors the bundle's three rules, and the brief adds `unknown`. The
inner CTM's faults already have rules that name each precisely (017), and a snapshot
wraps the CTM unchanged, so a second rule for the same fault would be a second account;
the `ctm.` prefix says where in the file. `resolve` is the server's step between the
guards and the run where a reference resolves, and a snapshot id or file is the
reference.

**Alternatives.** `snapshot.invalid` for every inner fault, naming the CTM's rule in the
message: one rule for many faults, and a hand user compiling a CTM `1` wrapped would see a
different identifier than for the same file unwrapped.

### R-04 The store: `snapshots/<id>.json`, two interfaces of one shape, never overwritten

**Decision.** `internal/snapshot.Store` is `Put(ctx, *Snapshot) (id string, err error)`,
`Has(ctx, id) (bool, error)`, `Path(id) string`, `Fetch(ctx, id) (*Snapshot, error)`;
`DirStore` keeps `<state root>/snapshots/<id>.json`, written to a temporary sibling and
renamed into place, so an entry is whole or absent. `Put` of an id the store holds
verifies the entry (re-reads it and re-hashes its body) and keeps it, writing nothing; an
entry that hashes to another id is `ErrIDMismatch{Path, Want, Got}`, which the server
files as `snapshot.id.mismatch` naming the store path, as the bundle store's is filed. The
stored bytes are the document's canonical encoding (R-01's conventions, the outer part
first). `bundle.Store` loses `PutCTM` and `DirStore` the sidecar. `lab.Paths` gains
`Snapshots`, and the server's and the worker's state root lines name it.

**Rationale.** D-014: a store small enough for object storage to replace; the shape is the
bundle store's so that M8 replaces one pattern twice. Two Go interfaces because the
currencies differ (a directory of files; one document), and a generic interface over
both would be an abstraction nothing needs yet. Never overwriting keeps the first take's
`observed_at` (brief, Decided), which a later `twin create --snapshot <id>` records.

**Alternatives.** One generic `Store[T]`: nothing needs it until M8, which is when the
two are replaced. Overwriting on `Put` (as `PutCTM` did): the stored document would move
with each take while its id did not.

### R-05 Where the server takes a snapshot, and when it files one

**Decision.** `internal/server/snapshot.go`: `takeSnapshot(ctx, paths, c *ctm.CTM)` wraps
the CTM (`snapshot.Take`), files it through the store and returns the snapshot, its id and
the store path; it is called by the create (live and dry run), by `intent read`, and by
the stages' pipeline, which gains `Take` between `Read` and `Compile`
(`stages.Pipeline{Read, Take, Compile, File}`; `PlanStage.SnapshotID`). The order is read →
take → compile → file the bundle. A refused read files nothing (FR-010). A refused
compile after a clean read leaves the snapshot filed: the CTM validated at its read, so
the input is worth keeping, and the bundle is what the compile refused. `fileCompiled`
loses its CTM parameter and `keepCTM` goes.

**Rationale.** One function, so the create, the dry run, the read, the plan, the step and
the rehearsal file alike (D-011's one code path). A snapshot is the input and a bundle the
output; filing the input before the output is the only order in which a refused compile
can leave something to inspect.

**Alternatives.** Taking the snapshot after the compile, so that nothing is filed on any
refusal: loses the input of a compile refused for a package the server lacks, which is
the case where the input is most worth having.

### R-06 The records: `twin.json` 9, the five documents, the frozen copies

**Decision.** `twin.json` moves to `9` (`$id` `…/contracts/twin/v9`): top level
`snapshot_id`, a string or an explicit `null`, required; `step.from.snapshot_id` and
`step.to.snapshot_id`, optional strings, present when the side's snapshot is known;
`source` gains `snapshot`. `NewRecord`'s rules: `intent` requires `observed_at` and takes
`snapshot_id` when given (a rebuild's provision gives none); `snapshot` requires
`observed_at` and `snapshot_id`, refuses a stage, and takes an `at` only as the envelope
has one; `bundle` refuses both. `NewStepRecord` moves the top level's `snapshot_id` to the
to side's. The findings document (`findings` `1`, additive) gains a top-level
`snapshot_id` on `twin.compile`, `intent.read`, `twin.create` and its dry run, and
`twin.step` (the target's), each beside `bundle_id`; `dry_run.follow.reason` gains
`snapshot`; `plan.stages[].snapshot_id` and `rehearsal.stages[].snapshot_id` are a string
or an explicit `null` beside `bundle_id`; `step.from` and `step.to` carry an optional
`snapshot_id`; `show.record.snapshot_id` is a string or `null` (null for a record of `8`
or earlier too, the text saying `(record 8)`), `show.record.source` gains `snapshot`, and
`show.record.step`'s sides the optional id. Frozen copies of the six files as they stand
before this feature go under `<package>/testdata/contracts/<feature>/`, where `<feature>`
is the one that last wrote the file (`git log -1 -- contracts/<file>` names it; expected
`017-dcim-reader` for `twin`, `show`, `findings` and `rehearsal`, `015-…` for `step`,
`014-…` for `stages`), in the packages that validate against them (`internal/lab` for
`twin`; `internal/server`, `internal/cli` and `internal/findings` for the rest), and
`frozenContractCopies` moves by the number added. Each package's additivity test loads
the frozen copy as it loads today's.

**Rationale.** FR-022 and FR-023: a record names its snapshot or says it has none, and
never invents one; an explicit `null` at the top level is the record's statement, as
`stage` and `step` make theirs, while a side's id is optional because a record of `8`
steps under this build with a from side that has none. The frozen-copy rule is
`internal/lab`'s, the one with four copies.

**Alternatives.** Sides with explicit `null`: `StepSide` is one type for the step's input,
the record and the record step's input, and the repository keeps queue payloads of
unchanged runs byte-identical by `omitempty` (017's `Scope`); an optional string keeps
that without a second type. A `twin.json` that stays `8` with a new optional key: the
record's contract is strict, and every milestone that added a key bumped the version.

### R-07 The client: `--snapshot <id|file>`, the guards, `--ctm` retired, the API

**Decision.** `twin create --snapshot <arg>`: an argument of 64 lowercase hex characters
is an id, sent as `args.snapshot`; anything else is a file path, read whole and sent as the
request's one file under that path with `args.snapshot` the path; a file the client
cannot read is its own `operation.failed`, exit 2, `reading snapshot: open <path>: …`,
before any connection. `twin compile --snapshot <file>` sends the file the same way under
`args.snapshot`; `--ctm` is gone (cobra's `unknown flag: --ctm`, exit 2, no request; the
help names `--snapshot`). The server's guards for a create, before any connection, after
`--branch or --stage or --snapshot is required`: `--snapshot` beside `--branch`,
`--stage`, `--at` or `--scope`, the first found in that order, is
`snapshot.flags.conflict` naming the flag (`--branch is meaningless with --snapshot: a
snapshot carries its own branch, at and scope`), exit 2 at `start`; `--interval` beside
`--snapshot` is `follow.flags.conflict`, `--interval is meaningless with --snapshot: a
twin built from a snapshot never follows`; `--no-follow` is accepted and changes nothing;
`--dry-run` is accepted. The API (`1`): `twin.create` gains `snapshot` and may carry one
file, under that path, only beside `snapshot`; a request carrying a file beside no
`snapshot`, or two, or one under another path, is refused before anything is parsed as
`twin.compile`'s are; `twin.compile`'s `ctm` becomes `snapshot` (a request carrying `ctm`
is `400`, `twin.compile takes no argument "ctm"`), pre-1.0 as 014 renamed `series`;
`intent.read` answers `snapshot.json` in its files frame.

**Rationale.** An id and a path are told apart by shape, as `twin provision` already
reads a directory named by an id; refusing an unreadable file on the client is M13's rule
for the CTM. A snapshot carries its branch, `at` and scope, so each flag that names one
is meaningless beside it, as beside `--stage`; `--interval` is the following's own rule
with the spec's sentence. The compile's argument is renamed with its flag because the
argument is the flag.

**Alternatives.** `--snapshot-id` and `--snapshot-file` as two flags: two spellings of one
reference. Keeping `ctm` as an API alias: a second name for one argument that no client
sends.

### R-08 `twin show` for a snapshot twin, and the create's dry run

**Decision.** A record whose `source` is `snapshot` is shown by its envelope and never as
following: with an `at`, `kind: pinned at <T>; not following; built from snapshot
<id8>…`; without, `kind: frozen; not following; built from snapshot <id8>…`; the note
`built from snapshot <id>` (the full id) joins the block's notes; the following branch of
the kind table is not taken for it whatever Schedule exists (a create stops following
before it stages, so none should). `from a bundle` stays the one kind for a record with
no envelope. The record line of every twin reads `record: <ref>, snapshot <id>, bundle_id
<id>, schema <hash>, <provenance clause>`, with `snapshot none` for a `9` naming none
and `snapshot none (record 8)` for an earlier record; `twin create` and `twin provision`
print the same line for the twin they made. The dry run's follow line reads `would not
follow (--snapshot given: a twin built from a snapshot never follows)`, reason `snapshot`.

**Rationale.** The brief's decision: a snapshot twin is of what its envelope says, and
no new kind; the note names the snapshot. Short ids in kind lines are the step's
convention; the record line prints full ids as it prints `bundle_id`.

### R-09 The text where an id is printed

**Decision.** A create and its dry run print `snapshot_id <id>  stored: <state
root>/snapshots/<id>.json` then `bundle_id <id>  stored: <state root>/bundles/<id>`, the
snapshot's line first, before the run's `start`. `intent read --out` prints `wrote
<file>: … (branch …, scope …, schema …); snapshot <id>, stored at <path>` — the summary
line as 017 has it, ending with the id and the store path. `twin compile --snapshot`
prints `wrote bundle to <dir> (<n> nodes, <m> links)`, `snapshot_id <id>` and `bundle_id
<id>`, filing nothing. `stage plan` prints `  snapshot_id <id>` above `  bundle_id <id>`
for each compiled stage. `twin step`'s twin line reads `twin: stage <s> (snapshot <id8>…,
bundle <id8>…), pinned at …`, `snapshot none` for a record naming none. The rehearsal's
table gains the column `snapshot` before `bundle`. No finding's message changes.

**Rationale.** The input before the output, everywhere; the findings' messages are stable
text that tests pin, and FR-022 is about records and documents.

### R-10 The workflows: inputs gain an optional id; no activity, marker or queue moves

**Decision.** `ProvisionInput.SnapshotID`, `RecordInput.SnapshotID`,
`StepSide.SnapshotID` and `RehearseStage.SnapshotID`, each `omitempty`; `wire.SourceSnapshot
= "snapshot"`. The provision workflow passes the id into the record input and otherwise
runs as it does for the rebuild's already-compiled input (`BundleID` set): host check
first, no read, no compile. Its `readAndCompile` branch stays for the recorded histories
and for no run this tree starts, and leaves with the reconcile at F-026. The Compile
activity no longer files a sidecar; `ReadIntent`, `bundles/.reads/`, `ReadOptions` and
the reconcile are untouched (FR-013). The step and rehearsal workflows carry the sides'
ids as data and branch on none of them.

**Rationale.** VIII: deterministic workflow code, idempotent activities passing references;
the repository's rule that an unchanged run's payloads stay byte-identical (`omitempty`).
SC-001 is met by the input's shape, which the server now always gives a create.

**Alternatives.** A version marker gating a new "no read" path: unnecessary, the shape
already exists for the rebuild. Removing `readAndCompile` now: the nine histories would
no longer replay.

### R-11 The create on the server: read, take, compile, file, start

**Decision.** `runCreate`, after the stage's resolution and before any run: the state
root; `observedAt` captured; `stage.Read` under `stage.ReadTimeout` (the read bound);
`takeSnapshot`; `stage.Compile`; `fileCompiled`; each refusal the document the command
ends with at `read` or `compile`, as the dry run places them, and no run started; then
`ProvisionInput{Source: intent, Branch, At, BundlePath, BundleID, ObservedAt, SnapshotID,
Scope, Stage, Follow}`. An Infrahub that fails or times out during the read is
`operation.failed` at `read` at once; the worker's retries and heartbeat no longer apply
to a create, as they do not to a step or a rehearsal (FR-010). The dry run adds the take
and its line. The create's answer prints the two `stored:` lines, then the run's events
from `start`.

**Rationale.** The step's and the rehearsal's path is the precedent (brief); the dry run
already does everything but the start.

### R-12 `twin create --snapshot`: fetch or file, compile, start; frozen by rule

**Decision.** An id: `store.Fetch`; absent is `snapshot.unknown` at `resolve`, exit 1, and
a corrupt entry `snapshot.id.mismatch` naming the store path. A file: `snapshot.Unmarshal`
(R-03), then `store.Put`, which keeps an entry already there, so a file of a snapshot the
store holds changes nothing and the twin records the stored document's `observed_at`.
Then `stage.Compile` and `fileCompiled`, and `ProvisionInput{Source: snapshot, Branch and
At from the envelope, BundlePath, BundleID, ObservedAt: the document's, SnapshotID, Scope:
the envelope's, Stage: nil, Follow: nil}`, `StopFollowing` set as on every run the
server starts. No request reaches Infrahub. The record's provenance comes from the staged
manifest as every record's does. The dry run reports the same with no start.

**Rationale.** FR-015 to FR-018 and the brief's decisions; the reader of a stored id is the
store, never the source of truth, which is the seam the feature proves.

### R-13 The stages' pipeline takes the snapshot; the step and the rehearsal carry it

**Decision.** `stages.build` calls `p.Take` after a clean read and before the compile;
`PlanStage.SnapshotID` is set once filed; `PlanStage.Block` writes it. `twin step`'s
`stepInput` fills `To.SnapshotID` from the built stage and `From.SnapshotID` from the
record; `rehearseStages` fills each `RehearseStage.SnapshotID`, the baseline's
`ProvisionInput.SnapshotID` and each step's sides; the report's `rehearsal.Stage` carries
it into the block. A stage refused at read files no snapshot and names `null`;
`rehearsal.steps.none` and the baseline rule are unchanged.

### R-14 The report's markdown

**Decision.** The table's header becomes `| stage | at | snapshot | bundle | step | wait |
verify | new verification failures | verdict |`; the cell is the short id or `—`; the
brief table (`| stage | verdict |`) and `fit`'s order of leaving parts out are unchanged,
so the `CommentMax` guard holds as it does. `internal/checks`' and `internal/rehearsal`'s
tests pin the header.

### R-15 The wrapped fixtures and the goldens

**Decision.** `testdata/snapshot/three-node.json`, `lossy.json` and `mixed.json` are the
three fixture CTMs wrapped by `snapshot.Take`, written with their ids (`6a8a77fc…`,
`91f06cd6…`, `37d7378a…` by §1.3; the implementation's own values stand). Tier 1 holds
each wrapped fixture's inner CTM equal to its `testdata/ctm/` file after canonical
marshal, its id equal to a recomputation, and its compile through `stage.Compile`
byte-identical to its golden; `internal/cli`'s compile test runs `twin compile --snapshot`
over them. The README's offline example compiles `testdata/snapshot/mixed.json` to
`ecb665f5…`.

### R-16 Tier 2: the reproducibility test and the stage taken twice

**Decision.** `TestPinnedReadReproducesItsBundle` (`internal/stage`) wraps each read with
`snapshot.Take` and asserts the three reads pinned at T share one snapshot id beside the
one bundle id, and the unpinned read after the change has another. A new
`TestStageTakenTwiceHasOneSnapshot` (`internal/server`, tag `contract`) makes a throwaway
`fylgja-test-*` branch, seeds it, opens a draft proposed change and marks one stage
through `testsupport`, then runs `runStagePlan` twice through `testOptions` and
`useStateRoot`: every compiled stage's `snapshot_id` is equal across the two plans, the
stored document's bytes and modification time are unchanged by the second plan, no
`bundles/<id>.ctm.json` is written, and the stages, then the proposed change, then the
branch are deleted at cleanup. `internal/stages` and `internal/checks` pass with the id in
their rows and the report's table (SC-006).

**Rationale.** The spec's "through the server's path": `runStagePlan` is that path, and
`internal/server` already holds a contract test composed the same way
(`rehearse_contract_test.go`).

### R-17 Tier 3

**Decision.** `compiled_id` reads with `--out` (now a snapshot file) and compiles with
`--snapshot`; `create_twin` reads `SID` from the create's `.snapshot_id`, asserts
`snapshots/$SID.json` exists and that no `bundles/*.ctm.json` is newer than the case's
start (`find -newer`), and expects `twin.json`'s `.snapshot_id==env.SID`; case 1's
`twin show` grep gains `snapshot $SID1, bundle_id $BID1`; case 5's rebuilt twin expects
`.show.record.snapshot_id==null`; case 7's steps expect `.step.to.snapshot_id` a string.
No case is added, and `PLATFORMS=nokia_srlinux` still ends `E2E-PARTIAL`.

### R-18 The documents

**Decision.** `contracts/cli.md` and `api.md` gain `## 018: snapshots`
([contracts/snapshot-commands.md](contracts/snapshot-commands.md)); `contracts/` gains
`snapshot.schema.json` and the six moved schemas ([contracts/formats.md](contracts/formats.md));
`docs/architecture.md` §2 (the pipeline names the snapshot), §3 (a Snapshot row in the
core objects' table), §4.2 (the CTM is the snapshot's body), §4.3 (the compiler's input is
a snapshot's CTM), §4.4 (the provision's steps begin at the host check for a create; the
sequence drawing; `ReadIntent` and `Compile` the reconcile's alone), §4.5 (the state root
tree gains `snapshots/` and loses the sidecar and its paragraph), §4.6 (the commands);
`docs/glossary.md` (Snapshot, Snapshot id, Snapshot store; Bundle store without the
sidecar; Frozen twin and Pinned gain the snapshot twin; Intent reference names the
snapshot as a reference); `docs/development.md` (the state root listing, the frozen
copies); `docs/c4/workspace.dsl` and `make diagrams`; `README.md` (the walk-through's
compile, the stage commands' lines); `CLAUDE.md` (Formats: snapshot `1`, `twin.json` `9`;
State: this feature and the fixture's snapshot id); `docs/verified-facts.md` (§1 here);
`docs/roadmap.md` (F-024 built at the close); `docs/decisions.md` and the constitution
(the operator's, §3).

### R-19 D-061 and Constitution 2.2.0

**Decision.** One entry, D-061, and a MINOR bump of VI to 2.2.0, as §3 drafts them; the
plan template's Constitution Check names 2.2.0. The operator accepts both at `analyze`,
before the records move (plan, Order of the work, 0).

### R-20 The record's `source`, and its comment

**Decision.** `intent | bundle | snapshot`. `intent`'s comment, "read and compile ran in
the run", becomes "created by `twin create --branch` or `--stage`: the server read and
compiled, or a check's rebuild did"; `snapshot` is "created by `twin create --snapshot`
from a stored or sent snapshot: no read"; `bundle` is unchanged.

### R-21 `twin verify` is left alone

**Decision.** `verify.twin.bundle_id` and verify's first line keep naming the bundle
alone: FR-022's list of five is the contract, and verify's block moves with the kind line
at F-026. Flagged for `analyze`.

### R-22 `probes` in version 1

**Decision.** `"probes": []`, required; the schema says `type: array, maxItems: 0` and
that 016 defines the element with a version bump. A non-empty list is `snapshot.invalid`.

### R-23 The limits, stated and not tested

**Decision.** The schema, the glossary and D-061 state both: a rebase re-stamps a
branch's content, so a stage resolved after a rebase reads differently or empty and gets
another id (`docs/verified-facts.md`, 10-16), and an artifact Infrahub re-rendered to
different bytes for unchanged data, never seen, would move the id. Neither is tested.

### R-24 No Infrahub skill

**Decision.** None loaded. The feature designs nothing in Infrahub: no kind, no object
file, no transform, no check; the one Python check that reads a plan (`fylgja-step`)
reads JSON a new key does not disturb.

## 3. Drafted for the operator

### 3.1 D-061 — The snapshot is the core's one input

To append to `docs/decisions.md` after D-060, under `<a id="d-061"></a>`:

> ## D-061 — The snapshot is the core's one input: a content-addressed wrap of the CTM, stored beside the bundles, and the bundle's CTM sidecar is retired
>
> **Status:** Accepted 2026-10-NN
>
> ### Context
>
> Two of the three live paths, `twin step` and `twin rehearse`, read, compile and file on
> the server and hand the worker a bundle id; `twin create` still read the branch inside
> its provision workflow (`ReadIntent`), through a CTM under `bundles/.reads/`, and the
> bundle store kept the CTM a create read as a sidecar beside its bundle. Until every
> workflow the core runs takes one input that is not a branch, the production shape's
> core (`docs/roadmap.md`, "The production shape"), which knows no branch, proposed
> change, stage or source of truth, is a drawing; and F-025's reader of NetBox, which
> cannot replay time, has nothing to address a stage by.
>
> ### Options considered
>
> - **A CTM `3` that gains the probe slot and loses `observed_at`.** One noun fewer, but
>   the CTM is the reader's contract (D-057) and would carry the core's concerns.
> - **A snapshot that holds the configurations beside the CTM**, as the roadmap first
>   wrote. The CTM has carried each device's artifact since M5; a second copy would be a
>   second place for one fact.
> - **A thin document wrapping an unchanged CTM `2`**, with an empty slot for probe
>   declarations and an id of its own: the hash of the body minus the read's
>   `observed_at`, by the rule the manifest already uses for `bundle_id` (D-023).
>
> ### Decision
>
> The snapshot, version `1`, wraps CTM `2` unchanged: `snapshot_version`, `snapshot_id`,
> the take's `observed_at`, the `ctm` and `probes`, required and empty until 016. The id
> is the SHA-256 of the body's canonical bytes with the inner `observed_at` left out and
> nothing else left out: the branch, the `at`, the schema hash, the scope, the mapping,
> the fidelity list, every artifact and the probe list are in it. It is filed by id under
> the state root's `snapshots/`, beside `bundles/`, behind a store of the bundle store's
> shape (D-014) that never overwrites, so two takes of one intent share one document, the
> first take's. The server takes the snapshot for every create, as it reads for a step
> and a rehearsal, and every workflow the core runs but the reconcile is started with a
> snapshot id and a bundle id and never a branch. `twin create --snapshot <id|file>` and
> `twin compile --snapshot <file>` take one directly; `intent read --out` writes one;
> `twin compile --ctm` is retired. A twin built from a snapshot is frozen by rule: its
> reference is a document, which does not move. Wherever a record names a bundle id it
> names the snapshot id beside it, except in the bundle, so bundle `5` and the goldens do
> not move. The bundle's CTM sidecar is retired: no build writes one, and those on disk
> are never read. The reconcile workflow is untouched until F-026.
>
> ### Consequences
>
> - The same intent read twice has one snapshot id, and one stage resolved twice has one,
>   while the branch's history stands: a rebase re-stamps the branch and moves every
>   stage's snapshot, and an artifact re-rendered to different bytes for unchanged data,
>   never seen, would move it. Both are limits, documented and not tested.
> - Where the source of truth cannot replay time, the snapshot's id addresses intent, and
>   a stage there is the snapshot Fylgja took when the operator marked it: Constitution VI
>   says so from 2.2.0, for F-025 to inherit.
> - `twin.json` `9` names the snapshot, or none for a twin `twin provision` built or a
>   following rebuild made; the five documents that name a bundle id name it too.
> - The compile that `twin compile` asks for runs on the snapshot's CTM, the goldens'
>   path (D-011); the CTM stays the reader's contract (D-057).
> - A snapshot holds configuration, as the CTM does: it lives in the store and crosses as
>   a file, never in a finding, a log line or a document.

### 3.2 Constitution 2.1.0 → 2.2.0

MINOR: Principle VI materially expanded. The sync impact line and the amended principle:

> - Version change: 2.1.0 → 2.2.0 (2026-10-NN, MINOR: Principle VI materially expanded).
>   VI's provenance sentence names the snapshot beside the CTM and the bundle;
>   `observed_at` appears neither in the bundle nor in the bytes a snapshot's id hashes;
>   and a sentence is added for the reader of a source that cannot replay time: the
>   snapshot's id addresses intent, and a stage there is the snapshot Fylgja took when the
>   operator marked it. Source: D-061. Templates: .specify/templates/plan-template.md's
>   Constitution Check names 2.2.0; its row VI reads the amended text.

> ### VI. Intent Is Addressed
> Every CTM, snapshot and bundle MUST record its provenance: branch, `at` if supplied, the
> schema hash Infrahub reports, the scope, and the mapping with the model version it read.
> `observed_at`, the UTC time the read began, MUST be recorded on every read, pinned or
> not, in the CTM, in the snapshot's outer part and in the twin directory, and MUST appear
> neither in the bundle nor in the bytes a snapshot's id hashes, so that the same intent
> hashes the same whenever it was read. When the operator supplies `at`, it MUST be passed
> verbatim on every query of the read. When the operator does not, Fylgja MUST NOT send an
> `at` it composed from a clock of its own; an `at` read from Infrahub — a stamp it
> returned, or the first instant after one — MAY be passed as the operator's would be,
> verbatim on every query, and is then recorded as the read's `at`. A read with neither
> has `observed_at` as the only record of when the intent was seen. `observed_at` is
> informational in every case, governs nothing when `at` is supplied, and any claim of
> reproducibility from it MUST say best-effort. Where the source of truth cannot replay
> time, the snapshot's id addresses intent, and a stage there is the snapshot Fylgja took
> when the operator marked it.
> *Rationale: D-001, D-012, D-023, D-045, D-061.*

The plan template's row VI: `Provenance recorded (branch, at, schema hash, scope, mapping
and model version in the bundle; observed_at in the CTM envelope, the snapshot's outer
part and twin.json, never in the bundle nor in the bytes a snapshot's id hashes); at
passed verbatim or not at all; where the source cannot replay time, the snapshot's id
addresses intent`.

## 4. Owed at implement

- The fixture's snapshot id as the shipped code computes it, read from `intent read
  --out` on `fylgja-fixture`, into `CLAUDE.md`'s State (quickstart §3).
- The three wrapped fixtures' ids as the shipped code computes them (R-15).
- The frozen copies' directories as `git log` names them (R-06), and
  `frozenContractCopies`.
- `docs/verified-facts.md`: §1.2 and §1.3 under 10-27, once tier 2 has held the
  stage-twice case.
- Tier 2's and tier 3's timings for `CLAUDE.md`'s Build and test paragraph.
- The worker and the server restarted on each rebuild and verified (quickstart §0).
