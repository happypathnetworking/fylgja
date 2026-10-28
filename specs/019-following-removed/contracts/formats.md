# The formats that move, and the frozen copies

**Feature**: `019-following-removed`. Each schema below is edited in place under
`contracts/`; its 018 shape is frozen where a test reads a document of that shape.

## 1. `contracts/twin.schema.json` → `twin.json` 10

- `$id` `…/contracts/twin/v10`; `twin_version` `"const": "10"`.
- `allOf`: the entry

  ```json
  { "if": { "properties": { "stage": { "type": "object" } } },
    "then": { "properties": { "source": { "const": "intent" },
                              "provenance": { "required": ["at"] } } } }
  ```

  becomes

  ```json
  { "if": { "properties": { "stage": { "type": "object" } } },
    "then": { "properties": { "provenance": { "required": ["at"] } } } }
  ```

- No property added or removed. Descriptions: the top-level paragraph gains "019:
  twin_version is 10. A stage no longer implies source intent: source says how the twin
  was created and a step keeps it, so a twin created from a snapshot and stepped to a stage
  names both. Nothing else is new."; `snapshot_id` and `source` lose the following rebuild
  (it is "an earlier build's rebuild").
- Frozen: the 9 file as `internal/lab/testdata/contracts/018-snapshots/twin.schema.json`.

## 2. `contracts/findings.schema.json` (stays `1`)

- `dry_run.follow` removed (and from `dry_run`'s properties; it was not required).
- `following` removed.
- The step enum loses `follow`.
- The verify block's `twin` gains `snapshot_id`: `{"type": ["string", "null"], "pattern":
  "^[0-9a-f]{64}$"}` for a string, required.
- The description's 019 sentence: the removals, pre-1.0, without a version move, as the API.
- Frozen: the 018 file as `internal/{cli,findings,server}/testdata/contracts/018-snapshots/findings.schema.json`.

## 3. `contracts/show.schema.json`

- `kind`: `"enum": ["none", "snapshot", "from_bundle", "diverged"]`.
- `following`, top-level `last_check` and `$defs/check` removed.
- `notes`' description loses the rebuild and the stopped following.
- Frozen: the 018 file as `internal/{cli,findings,server}/testdata/contracts/018-snapshots/show.schema.json`.

## 4. `contracts/api.schema.json`

- `$defs/args/$defs/twin.create`: `interval` and `no_follow` removed (it keeps
  `additionalProperties: false`).
- `$defs/args/$defs/twin.step`: gains `"snapshot": {"type": "string"}`.
- The request's `files` description: `twin.step` takes one beside a `snapshot` path.
- Not frozen: the API's own tests read the current file only.

## 5. `contracts/step.schema.json`

Unchanged: `$defs/side` already admits `"stage": null` with `snapshot_id` optional. Its
description gains: "019: a side names no stage when the step's target was a snapshot
(`twin step --snapshot`), or when the twin was built from one and has not stepped to a
stage".

## 6. The frozen copies, summarised

| Package | New directory | Files |
|---|---|---|
| `internal/lab` | `018-snapshots/` | `twin.schema.json` |
| `internal/cli` | `018-snapshots/` | `findings.schema.json`, `show.schema.json` |
| `internal/findings` | `018-snapshots/` | `findings.schema.json`, `show.schema.json` |
| `internal/server` | `018-snapshots/` | `findings.schema.json`, `show.schema.json` |

Seven copies; `frozenContractCopies` 49 → 56, unless implement finds a package whose tests
read no 018-shaped document, in which case the copy is not made and the count says so.
Every copy of one `<feature>/<name>` is byte-equal (`TestFrozenContractCopiesAgree`).
