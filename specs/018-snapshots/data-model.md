# Data model: Snapshots, the core's one input

**Feature**: `018-snapshots` · **Plan**: [plan.md](plan.md) · **Research**:
[research.md](research.md) (R-01…R-24) · **Contracts**:
[snapshot.schema.json](contracts/snapshot.schema.json),
[snapshot-commands.md](contracts/snapshot-commands.md), [formats.md](contracts/formats.md)

What the feature adds or moves, entity by entity: its fields, its rules, and where it
lives. Names in code are the plan's; the JSON keys, identifiers and text are the
contracts'.

## 1. The snapshot (`internal/snapshot`)

The core's one input: a document of version `1`, stored and sent as JSON.

| Part | Field | JSON | Hashed | Rule |
|---|---|---|---|---|
| outer | `Version` | `snapshot_version` | no | `"1"`; read first, on its own; another or none is `snapshot.version.unsupported` |
| outer | `ID` | `snapshot_id` | no | 64 lowercase hex characters, the hash of the body (§2); required in a document Fylgja writes, optional in a file a client sends: computed when absent, `snapshot.id.mismatch` when present and not the body's |
| outer | `ObservedAt` | `observed_at` | no | the take's, UTC with six fractional digits (`stage.ObservedAtFormat`); equal to the inner CTM's in version 1; optional in a file a client sends, filled from the inner CTM when absent, `snapshot.invalid` when present and not of the form or not equal |
| body | `CTM` | `ctm` | yes, minus its `envelope.observed_at` | one CTM `2`, read by `ctm.Unmarshal` and refused by its own rules with the object prefixed `ctm.`; normalised by `ctm.Normalize` before it is hashed or written |
| body | `Probes` | `probes` | yes | a list, required and empty in version 1 (`maxItems: 0`); absent, null or non-empty is `snapshot.invalid`; 016 defines the element and bumps the version |

**Operations**:

- `Take(c *ctm.CTM) *Snapshot` (pure): normalises a copy of `c`, sets `Version`, copies
  `c.Envelope.ObservedAt` to `ObservedAt`, `Probes` to `[]`, computes `ID`.
- `Marshal(*Snapshot) ([]byte, error)`: the stored form, canonical: the outer part first
  (`snapshot_version`, `snapshot_id`, `observed_at`), then `ctm`, then `probes`; struct
  field order, two-space indent, LF, trailing newline (the CTM's conventions).
- `Unmarshal([]byte) (*Snapshot, error)`: strict, in R-03's order; returns
  `*VersionError{Got}`, `*InvalidError{Field, Message}`, the CTM's `*ctm.VersionError` and
  `*ctm.MissingError` (their `Field` prefixed `ctm.`), or `*IDMismatchError{Declared,
  Computed}`.
- `Hashed(*Snapshot) []byte`: the hashed bytes (§2); `ID(*Snapshot) string` is their
  SHA-256 in lowercase hex; `IsID(string) bool` is the 64-hex shape (`bundle.IsID`'s rule).
- `Load(path)` and `Save(*Snapshot, path)` for tests and the client's files.

**Invariants**: `s.ObservedAt == s.CTM.Envelope.ObservedAt`; `s.ID == ID(s)`;
`len(s.Probes) == 0`; a snapshot that `Unmarshal` accepts compiles through `stage.Compile`
to the bundle its CTM compiles to, or is refused by the CTM's validation rules there.

## 2. The snapshot id

`snapshot_id` is the SHA-256, 64 lowercase hex characters, of the **hashed bytes**:

```
{
  "ctm": {
    "ctm_version": "2",
    "envelope": {
      "branch": …, ["at": …,] "schema_hash": …, "scope": …,
      "mapping": {"reader": …, "model": …, "version": …},
      "fidelity": […]
    },
    "devices": […],
    "links": […]
  },
  "probes": []
}
```

the CTM normalised and encoded as `ctm.Marshal` encodes one, its envelope without the
`observed_at` key, wrapped with `probes`, two-space indent, a trailing newline. The hashed
bytes differ from the stored bytes and are never stored. Implemented by a `hashed`
envelope type held to `ctm.Envelope` by a reflection test (every field but `ObservedAt`,
same tags, same order). Hand recipe, exact for strings holding none of `<`, `>`, `&`:

```
jq --indent 2 'del(.snapshot_version, .snapshot_id, .observed_at, .ctm.envelope.observed_at)' snapshots/<id>.json | sha256sum
```

Eight characters and an ellipsis in text (`576933ec…`), the full id in records, JSON and
the `stored:` lines. Candidates by research §1.3: the live fixture `576933ec…`;
`three-node` `6a8a77fc…`, `lossy` `91f06cd6…`, `mixed` `37d7378a…`.

**What moves it**: any byte of any artifact, any fidelity row, the branch, the `at`, the
schema hash, the scope, the mapping, a device, a port or a link. **What does not**:
`observed_at`, the order of any list, the outer part.

## 3. The snapshot store (`internal/snapshot`)

```go
type Store interface {
    Put(ctx context.Context, s *Snapshot) (id string, err error)  // files s under its id; keeps an entry already there after verifying it; never overwrites
    Has(ctx context.Context, id string) (bool, error)             // an entry exists and hashes to id; a corrupt entry is false
    Path(id string) string                                        // <root>/<id>.json
    Fetch(ctx context.Context, id string) (*Snapshot, error)      // reads and verifies the entry; ErrIDMismatch when its body hashes to another id
}
```

`DirStore` on `<state root>/snapshots/`, created on first `Put`; a temporary sibling then
a rename, mode `0644`; `ErrIDMismatch{Path, Want, Got}` with the bundle store's wording.
Kept for ever, as bundles are. `lab.Paths.Snapshots` names the directory; the server's and
the worker's state root lines name it beside `bundles` and `twin`.

**The bundle store** (`internal/bundle`): `Store` loses `PutCTM`; `DirStore` writes no
`<bundle_id>.ctm.json` and reads none; `bundles/.reads/` stays, the reconcile's alone.

## 4. The server's take and filing (`internal/server/snapshot.go`)

`takeSnapshot(ctx, paths lab.Paths, c *ctm.CTM) (s *snapshot.Snapshot, path string,
list findings.List, err error)`: `snapshot.Take`, then the store's `Put`; a corrupt entry is
`snapshot.id.mismatch` at the caller's step naming the store path; any other failure is
the caller's `operation.failed`. Called by:

| Caller | Order | Files | Refusals' step |
|---|---|---|---|
| `twin create --branch|--stage` (`runCreate`) | resolve → read → **take** → compile → file bundle → start | the snapshot, then the bundle | `read`, `compile`; `resolve` for a stage |
| `twin create --dry-run` (`runCreateDryRun`) | as the create, then the host check and the report | the same | the same |
| `twin create --snapshot <id>` (`resolveSnapshot`) | guards → fetch → compile → file bundle → start | the bundle | `resolve` (`snapshot.unknown`, `snapshot.id.mismatch`), `compile` |
| `twin create --snapshot <file>` | guards → unmarshal → **put** → compile → file bundle → start | the snapshot (an entry already there kept), then the bundle | `resolve` (the snapshot's rules), `compile` |
| `intent read --out` (`read`) | resolve → read → **take** → answer | the snapshot | none (M1's operations carry no step) |
| `stage plan`, `twin step`, `twin rehearse` (`stages.build`) | resolve → read → **take** → compile → file bundle, per stage | the snapshot, then the bundle, per stage | per stage, at `read` and `compile` |
| `twin compile --snapshot <file>` (`runCompile`) | unmarshal → compile → answer | nothing | none |

A refused read files nothing; a refused compile after a clean read leaves the snapshot
filed (R-05).

**The stages' pipeline**: `stages.Pipeline{Read, Take, Compile, File}`; `Take func(ctx,
c *ctm.CTM) (id string, list findings.List, err error)`; `File` loses its CTM parameter;
`PlanStage.SnapshotID string` set once filed, `""` when refused before it.

## 5. The records

### 5.1 `twin.json` 9 (`internal/lab`, `internal/lab/wire`)

| Field | JSON | Type | Rule |
|---|---|---|---|
| `TwinRecord.SnapshotID` | `snapshot_id` | string or explicit `null` | the snapshot the twin was built from or last stepped to; `null` for a twin `twin provision` built, one a following rebuild made, and a record of `8` or earlier |
| `TwinRecord.Source` | `source` | `intent`, `bundle`, `snapshot` | `snapshot`: created by `twin create --snapshot`; `intent`'s comment moved (R-20) |
| `StepSide.SnapshotID` | `step.from.snapshot_id`, `step.to.snapshot_id` | optional string | present when the side's snapshot is known; a record of `8` stepping has none on its from side |
| `TwinVersion` | `twin_version` | `"9"` | |

`NewRecord` (by `Source`): `intent`: `ObservedAt` required, `SnapshotID` as given (`""`
for a rebuild's provision); `snapshot`: `ObservedAt` and `SnapshotID` required, `Stage`
refused, `At` as the envelope has it; `bundle`: `ObservedAt` and `SnapshotID` refused,
`Stage` refused. `SnapshotID` when given must satisfy `snapshot.IsID`. `NewStepRecord`: a
stepped or unchanged step moves `SnapshotID` to `To.SnapshotID` (`null` when empty); a
diverged step keeps the previous record's; both sides are kept in `step`. `ReadRecord`
reads an `8` with `SnapshotID` nil and no side ids.

### 5.2 The workflow inputs (`internal/provision`, `internal/lab/wire`)

| Type | Field | JSON | Who sets it |
|---|---|---|---|
| `ProvisionInput` | `SnapshotID` | `snapshot_id,omitempty` | the server, on every create; empty on a rebuild's provision and on `twin provision` |
| `ProvisionInput` | `Source` | `source` | `wire.SourceSnapshot` for `--snapshot` |
| `wire.RecordInput` | `SnapshotID` | `snapshot_id,omitempty` | the provision workflow, from its input |
| `wire.StepSide` | `SnapshotID` | `snapshot_id,omitempty` | the server's `stepInput` and `rehearsedStep`; the record step copies it into `twin.json` |
| `RehearseStage` | `SnapshotID` | `snapshot_id,omitempty` | the server's `rehearseStages` |

No workflow, activity, budget, marker or queue is added; the Compile activity stops
filing a sidecar; the provision workflow's `readAndCompile` branch stays for the
recorded histories.

### 5.3 The findings document (`findings` `1`, additive)

| Where | Key | Type | On |
|---|---|---|---|
| top level | `snapshot_id` | string | `twin.compile` (ok), `intent.read` (ok), `twin.create` and its dry run (once the take completed), `twin.step` and its dry run (the target's) |
| `dry_run.follow.reason` | | enum + `snapshot` | `twin.create --snapshot --dry-run` |
| `plan.stages[]` | `snapshot_id` | string or `null` | `stage.plan`, beside `bundle_id` |
| `step.from`, `step.to` | `snapshot_id` | optional string | `twin.step` |
| `rehearsal.stages[]` | `snapshot_id` | string or `null` | `twin.rehearse`, beside `bundle_id` |
| `show.record` | `snapshot_id` | string or `null` | `twin.show`; `null` for a `9` naming none and for an `8` or earlier |
| `show.record.source` | | enum + `snapshot` | |
| `show.record.step.from`, `.to` | `snapshot_id` | optional string | |

Each is a struct field in `internal/findings/render.go` (`Document.SnapshotID string
omitempty`; `PlanStage.SnapshotID *string`; `RehearsalStage.SnapshotID *string`;
`ShowRecord.SnapshotID *string`; `StepSideBlock.SnapshotID string omitempty`;
`FollowReasonSnapshot`). The schemas move as [formats.md](contracts/formats.md) says, each
with a frozen copy.

### 5.4 The rehearsal's report (`internal/rehearsal`)

`rehearsal.Stage.SnapshotID string` into `findings.RehearsalStage.SnapshotID`; the table's
column `snapshot` before `bundle`, the short id or `—`; `fit` unchanged.

## 6. The identifiers (`internal/findings/finding.go`)

Five added; no status, step or exit is new.

| Rule | Severity, exit, step | Object | When |
|---|---|---|---|
| `snapshot.invalid` | rejection, 1, none on `twin compile`; `resolve` on `twin create --snapshot <file>` | the field (`probes`, `snapshot_id`, `observed_at`, `ctm`) or the file | the outer shape is not version 1's: an unknown key, `ctm` absent or not an object, `probes` absent or not empty, `snapshot_id` not 64 hex, `observed_at` not of the form or not the inner CTM's |
| `snapshot.version.unsupported` | rejection, 1, none / `resolve` | the file | `snapshot_version` is not `"1"`, or absent; names the version read and `"1"` |
| `snapshot.id.mismatch` | rejection, 1, none / `resolve`; `compile` for a corrupt store entry | the file, or the store path | a declared `snapshot_id` is not the body's hash, naming both; or an entry under the id hashes to another, naming the path and both |
| `snapshot.unknown` | rejection, 1, `resolve` | the id | `twin create --snapshot <id>` names an id the store does not hold; names the store's directory |
| `snapshot.flags.conflict` | rejection, 2, `start` | the flag | `--snapshot` beside `--branch`, `--stage`, `--at` or `--scope`, the first found in that order; before any connection |

Reused: `follow.flags.conflict` for `--interval` beside `--snapshot` (exit 2, `start`);
`ctm.version.unsupported` and `data.required.missing` for the inner CTM, the object
prefixed `ctm.`; validation's rules at compile; `bundle.id.mismatch` for the bundle store.

## 7. The client (`internal/cli`) and the API (`internal/api`, `internal/server/handlers.go`)

| Command | Flag | The client | The server |
|---|---|---|---|
| `twin create` | `--snapshot <id|file>` | 64 lowercase hex: sends `args.snapshot` = the id; else reads the file and sends it as the request's one file under its path, `args.snapshot` = the path; an unreadable file is its own `operation.failed` (exit 2) before any connection | the guards (R-07); an id fetched, a file unmarshalled and filed; the create from it |
| `twin compile` | `--snapshot <file>` (required), `--out <dir>` | reads the file once both flags are given; writes the bundle that comes back; `--ctm` is an unknown flag | `args.snapshot` and the one file under that path, as `ctm` was; the snapshot's rules; `snapshot_id` and `bundle_id` in the document; files nothing |
| `intent read` | `--out <file>` | writes the snapshot that comes back (`snapshot.json` in the files frame) atomically | reads, takes, files, answers with the document and the summary |

The API stays `1`: `twin.create` gains `snapshot` and may carry one file beside it;
`twin.compile`'s argument `ctm` becomes `snapshot`; `intent.read`'s files frame carries
`snapshot.json`. `checkRequired`/`checkFiles` (`handlers.go`): `twin.create` takes at most
one file, only with `snapshot` and under that path; `twin.compile` takes exactly one under
`args.snapshot`.

## 8. `twin show` (`internal/server/show.go`)

- The record line: `record: <ref>, snapshot <id|none|none (record <v>)>, bundle_id <id>,
  schema <hash>, <provenance clause>`.
- The kind line of a `source: snapshot` record: `pinned at <T>; not following; built from
  snapshot <id8>…` or `frozen; not following; built from snapshot <id8>…`; the note `built
  from snapshot <id>`; never `following`.
- The step line and the rest unchanged.

## 9. Fixtures and tests

| File | What |
|---|---|
| `testdata/snapshot/three-node.json`, `lossy.json`, `mixed.json` | the fixture CTMs wrapped by `snapshot.Take`, with their ids |
| `internal/snapshot/*_test.go` | the id's rules (R-01, R-02), the four refusals, the store's never-overwrite and `ErrIDMismatch`, the reflection test over the envelope, the independent recomputation (a test-local struct) |
| `internal/compiler` or `internal/stage` golden test | each wrapped fixture compiles to its golden byte for byte |
| `internal/lab/twin_test.go` | `twin.json` `9` against the contract; an `8` against the frozen copy; `NewRecord`'s rules by source |
| `internal/server/*_test.go` | the create's read/take/compile/file over faked pipelines; `--snapshot` guards and refusals; the dry run's lines; `intent read`'s file and filing; `twin compile --snapshot`; the show lines |
| `internal/cli/*_test.go` | `--snapshot` id vs file, the unreadable file, `--ctm` unknown; `--out` writes a snapshot |
| `internal/findings`, `internal/rehearsal` tests | the documents against the moved contracts and the frozen copies; the table's column |
| `internal/provision/workflow_replay_test.go` | the nine histories replay |
| tier 2 | `TestPinnedReadReproducesItsBundle` (+ snapshot ids); `TestStageTakenTwiceHasOneSnapshot` (`internal/server`) |
| tier 3 | `scripts/e2e.sh` as R-17 |

## 10. The documents

[research.md](research.md) R-18 lists them; the C4 model gains the server's `snapshot`
component ("The snapshot: the document, its id, its validation, the store.",
`internal/snapshot`) and the container `Snapshot store` (`<state root>/snapshots/<snapshot_id>.json`),
with `handlers -> snapshot "Takes, validates and files snapshots"`, `stages -> snapshot
"Takes each stage's snapshot"`, `server -> snapshot store "Files and reads snapshots"`;
the worker's `workflows` description says the provision, step and rehearsal take a
snapshot id and a bundle id and the reconcile alone reads; the deployment's state root
names `snapshots/`.
