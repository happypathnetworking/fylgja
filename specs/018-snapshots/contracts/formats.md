# The formats that move, and the frozen copies

**Feature**: `018-snapshots` · **Plan**: [plan.md](../plan.md) · **Research**:
[research.md](../research.md) (R-06, R-14, R-15) · **Commands**:
[snapshot-commands.md](snapshot-commands.md)

One rule: wherever a record names a bundle id, the snapshot id sits beside it, except in
the bundle. Bundle `5`, the manifest, CTM `2`, PSP `0.7` and the three goldens do not
move. Every change below is additive to its document's reader: a key added, an enum
widened, a version bumped where the contract is strict and versioned.

## 1. `contracts/snapshot.schema.json` (new)

[snapshot.schema.json](snapshot.schema.json), `$id`
`https://github.com/happypathnetworking/fylgja/contracts/snapshot/v1`, under this
repository's URL ([D-055](../../../docs/decisions.md#d-055)). It references CTM 2 by its
`$id`. Its description says in one sentence that the bytes the id hashes differ from the
stored bytes, and gives the hand recipe.

## 2. `contracts/twin.schema.json` → `twin.json` 9

`$id` `…/contracts/twin/v9`; `twin_version` `const "9"`; the title and description gain
their 018 sentence:

> 018: twin_version is 9. The record names the snapshot the twin was built from or last
> stepped to, `snapshot_id`, or null for a twin twin provision built, one a following
> rebuild made, or a record of 8 or earlier, which reads with none; `source` gains
> `snapshot`, a twin twin create --snapshot built from a stored or sent snapshot, which
> had no read of a branch; `step.from` and `step.to` may name each side's snapshot,
> `snapshot_id`, absent where the side's is not known (the from side of an 8 record that
> stepped). Nothing else is new.

| Path | Change |
|---|---|
| `snapshot_id` | added, required: `{"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}` |
| `source` | enum `["intent", "bundle", "snapshot"]`; the description rewords `intent` ("created by twin create --branch or --stage: the server read and compiled, or a check's rebuild did") and adds `snapshot` |
| `step.properties.from`, `step.properties.to` | gain optional `snapshot_id` (string, the pattern); `required` unchanged |
| `observed_at` | description: "… when the run's input carried a read's time: a create's, a snapshot's stored take, or a check's; null when it did not (twin provision)" |

**Frozen copy**: `internal/lab/testdata/contracts/017-dcim-reader/twin.schema.json`, the
`8` as 017 wrote it (R-06; `twinSchemaOf(t, "017-dcim-reader")`), beside `009-stepping`
(4), `010-verify` (5), `014-…` (6) and `015-…` (7). `lab/twin_test.go` validates a `9`
NewRecord and NewStepRecord write against the current contract, and the `8` fixtures
against the frozen copy; `ReadRecord` reads an `8` with `SnapshotID` nil.

## 3. `contracts/findings.schema.json` (stays `1`)

| Path | Change |
|---|---|
| `properties.snapshot_id` | added, optional: `{"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "twin.compile (status ok), intent.read (status ok), twin.create and its dry run (once the take completed), twin.step and its dry run (the target's): the snapshot's identity, beside bundle_id (018)."}` |
| `properties.dry_run.properties.follow.properties.reason.enum` | gains `snapshot` |
| the description | gains its 018 sentence: `snapshot_id` beside `bundle_id`; `dry_run.follow.reason` `snapshot`; the five identifiers; the blocks that move are each schema's own |

The `step`, `plan`, `rehearsal`, `show` and `stages` blocks are referenced by their `$id`s
and change in their own files.

**Frozen copies**: `findings.schema.json` as 017 left it under
`internal/findings/testdata/contracts/017-dcim-reader/`, `internal/server/…`, and
`internal/cli/…` (each package that validates documents against a feature's contract;
the copies byte-equal, `TestFrozenContractCopiesAgree`), with the four block schemas the
frozen findings contract references under their `$id`s (`show`, `stages`, `step`,
`rehearsal`) beside it in the same directories, so a document of a twin with no snapshot
(a `twin provision`) still validates under 017's contract: the additivity test.
`frozenContractCopies` moves from 33 by the number of files added.

## 4. `contracts/show.schema.json`

| Path | Change |
|---|---|
| `properties.record.properties.snapshot_id` | added, required: `{"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$", "description": "018: the snapshot the record names, as twin.json 9's snapshot_id; null for a 9 naming none and for a record of 8 or earlier, whose record line says (record 8)"}`; `record.required` gains `snapshot_id` |
| `properties.record.properties.source.enum` | gains `snapshot` |
| `properties.record.properties.step.properties.from` and `.to` | gain optional `snapshot_id` |
| `properties.kind` | unchanged (`none`, `following`, `frozen`, `pinned`, `from_bundle`, `diverged`): a `--snapshot` twin is `pinned` or `frozen` |
| `properties.notes` | unchanged; the note `built from snapshot <id>` is one of them |
| the description | gains its 018 sentence |

## 5. `contracts/stages.schema.json`

| Path | Change |
|---|---|
| `$defs.plan_stage.properties.snapshot_id` | added, required: `{"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$", "description": "018: the stage's snapshot once its read was filed; null when the stage was refused at resolution or read"}`; `plan_stage.required` gains it |
| `$defs.step` (the pair) | unchanged: `from_bundle_id`, `to_bundle_id` name the bundles the diff is between |
| `$defs.row`, `$defs.record`, `$defs.list` | unchanged: `stage list` neither reads nor compiles |

## 6. `contracts/step.schema.json`

| Path | Change |
|---|---|
| `$defs.side.properties.snapshot_id` | added, optional: `{"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "018: the side's snapshot; absent on a from side whose record names none (a record of 8)"}` |
| the description | gains its 018 sentence |

## 7. `contracts/rehearsal.schema.json`

| Path | Change |
|---|---|
| `$defs.stage.properties.snapshot_id` | added, required: `{"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$", "description": "018: the stage's snapshot, beside bundle_id; null when the stage was refused"}`; `stage.required` gains it |
| the description | gains its 018 sentence, and that the markdown's table carries a `snapshot` column before `bundle` |

## 8. `contracts/api.schema.json` and `api.md`

| Path | Change |
|---|---|
| `$defs.args.twin.create.properties.snapshot` | added: `{"type": "string", "description": "--snapshot as given: a snapshot id (64 lowercase hex characters) the store holds, or the path of the file the request carries"}` |
| `$defs.args.twin.compile.properties` | `ctm` renamed `snapshot`; `required` likewise |
| `$defs.request.properties.files.description` | gains `twin.create: the snapshot, under the path snapshot gives, when snapshot is a path` and reads `twin.compile: the snapshot, under the path given` |
| the operations table in `api.md` | `twin.create`: `args` + `snapshot`, files in "the snapshot, when --snapshot is a file"; `twin.compile`: `snapshot`, `out`; `intent.read`: files out "the snapshot" |

## 9. The frozen copies, summarised

| File | Frozen as | Under | Validated by |
|---|---|---|---|
| `twin.schema.json` | `8` | `internal/lab/testdata/contracts/017-dcim-reader/` | `lab/twin_test.go` |
| `findings.schema.json` | 017's | `internal/findings/…`, `internal/server/…`, `internal/cli/…` `testdata/contracts/017-dcim-reader/` | each package's additivity test over a document with no snapshot |
| `show.schema.json` | 017's | the same three | with the findings contract |
| `stages.schema.json` | 014's, as 017 left it | the same three | with the findings contract |
| `step.schema.json` | 015's, as 017 left it | the same three | with the findings contract |
| `rehearsal.schema.json` | 017's | the same three | with the findings contract |

The directory is the feature that last wrote the file, as `git log -1 --
contracts/<file>` names it (R-06); implement confirms each. A copy is never edited.

## 10. The rehearsal's markdown (not a schema)

The table's header and a row:

```
| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |
|---|---|---|---|---|---|---|---|---|
| change-1/seeded | 2026-10-… | 1a2b3c4d… | 5e6f7a8b… | created | settled after 3.1s | … | — | baseline |
```

`—` where the stage was refused. The brief table (`| stage | verdict |`) and the
`CommentMax` guard are unchanged; `internal/rehearsal/markdown_test.go` and
`internal/checks` pin the header.

## 11. The wrapped fixtures (`testdata/snapshot/`)

`three-node.json`, `lossy.json` and `mixed.json`: each `testdata/ctm/<name>.json` wrapped
by `snapshot.Take`, with `snapshot_version`, `snapshot_id` and `observed_at` (the CTM's),
written in the store's canonical form. Tier 1 holds the inner CTM equal to the
`testdata/ctm/` file after canonical marshal, the id equal to a recomputation, and the
compile equal to the golden; the README's offline example compiles `mixed.json` to
`ecb665f5…`. Candidate ids by research §1.3: `6a8a77fc…`, `91f06cd6…`, `37d7378a…`.
