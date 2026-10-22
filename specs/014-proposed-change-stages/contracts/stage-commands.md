# Contract: the stage commands, the API's operations, the findings blocks and `twin.json` 6

Extends [contracts/cli.md](../../../contracts/cli.md) and [contracts/api.md](../../../contracts/api.md)
as 014 leaves them; at the close each gains a section "014: the stage surface" that says
what this file says. **Everything not named here is as M13 left it.** Identifiers, exit
statuses and the JSON documents are the contract; text is illustrative except where quoted.

## The commands

```
fylgja stage list  [--branch <b>]             # every open proposed change's stages, or one's; marks the twin's
fylgja stage plan  --branch <b>               # reads and compiles each stage; the step between each pair
fylgja twin create --stage <branch>/<label>   # the pinned run of the reference the stage resolves to; never follows
fylgja twin step   [--stage <branch>/<label>] [--allow-restart] [--wait <duration>] [--dry-run]
fylgja intent read --stage <branch>/<label> --out ctm.json
fylgja schema check --branch <b>              # also says whether the default branch has the stage kind and its extension
```

`waypoint list`, `waypoint plan` and `--waypoint` are gone: `fylgja --help` names none, and
`fylgja waypoint list` is cobra's `unknown command`, exit 2, with no request.

Each is a client's command: one request, the frames printed, the exit by the document.
`stage list` and `stage plan` need Infrahub and (the plan) the bundle store, and no lab,
worker or workflow service. Every refusal with an identifier is the server's.

### `stage list [--branch <b>]`

Text: a heading per proposed change, then one line per stage with the reference, the branch
and the at padded so the ats, the sources and the descriptions line up within the proposed
change whatever each at's width (a branch's origin ends `Z`, a stamp `+00:00`), the
description quoted, and the twin's row marked:

```
proposed change "third link" (18df…) on branch change-1, draft (4 stages)
  change-1/branch-point  main      at 2026-10-16T17:20:19.944651+00:00 (branch point)  ""
  change-1/cabled        change-1  at 2026-10-16T17:25:30.118244+00:00 (written)       "after the link is cabled"  ← twin
  change-1/live          change-1  at 2026-10-16T17:30:00.000000+00:00 (given)         "after its configuration is live"
  change-1/head          change-1  at 2026-10-16T17:30:11.884302+00:00 (head)          ""
```

With no open proposed change: `no open proposed change` (or `branch b: no open proposed
change` with `--branch`), exit 0, `stages.rows == []`. Beside a diverged record the mark
reads `← twin (diverged towards change-1/live)`. Orphans print after the proposed changes:
`orphaned: stage "cabled" (18df…) names no proposed change`. Every stage has its row: one
nothing names an `at` for prints `at unresolved` and has no `at` in its row, with the
warning `stage.at.unresolved` (the head of a branch holding neither a stamp nor an intent
event); a source
branch deleted under its open proposed change lists its marks at their own `at`s and its
branch point and head unresolved, with one warning `stage.unknown` naming the branch, until
Infrahub cancels it, every other proposed change listed as usual. The heading's count is
the rows'. Exit 0 with warnings; exit 1 when a reserved label is among the rows
(`stage.label.reserved`) or the kind is absent; exit 2 when Infrahub cannot be read
(`operation.failed` at `resolve`).

JSON: `stages` block (`stages.schema.json` `$defs/list`), the findings.

### `stage plan --branch <b>`

Text: the heading, then each stage as it finishes and each step as it is known:

```
proposed change "third link" (18df…) on branch change-1 → main, draft (4 stages)
change-1/branch-point: refused (contract.node.missing)
  rejection contract.node.missing [step read] main: branch defines FylgjaContract but holds no instance of it
step change-1/branch-point → change-1/cabled (— → 5c6c1d96…): not computed (change-1/branch-point was refused)
change-1/cabled: branch change-1 at … (written), "after the link is cabled"
  bundle_id 5c6c1d96…
  …
```

(each compiled stage: `change-1/cabled: branch change-1 at … (written), "after the link is
cabled"`, `  bundle_id …`, `  read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3
artifacts, 0 lossy mappings, 0 shared ports`; a refused stage: `change-1/live: refused
(stage.artifact.stale)` then its findings indented, each in the document's text-line shape,
`<severity> <rule> [step <step>] <object>: <message>`, the bracket for a finding with a
step; a step: `step.Pair.Text()` as M10
printed it, both ids beside it, `—` for a side that has none, `unchanged` when the two
bundles differ in provenance alone, which the step from a mark written after the last
regenerate to the head always is, and `unchanged; the two are one bundle` when two stages
resolve to one `(branch, at)`). Exit 0 when every stage compiled, whatever the warnings; 1
when any was refused; 2 when the listing failed. A stage whose resolution, read, compile or
filing could not run is `failed` (`operation.failed` at its step) and the plan goes on, the
steps touching it not computed; that exits 1 as well, since the plan ran and reported every
stage, where 2 is an operation that did not run.
`--branch` is required (`--branch is required`, exit 2, no request).

JSON: `plan` block (`$defs/plan`), the findings (every stage's, in order).

### `--stage` on `twin create` and `intent read`

The resolved line first, wherever a reference resolved, before the run or the read:

```
stage change-1/cabled: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"
stage change-1/branch-point: main at 2026-10-16T17:20:19.944651+00:00 (branch point)
stage change-1/head: branch change-1 at 2026-10-16T17:30:11.884302+00:00 (head)
```

Then the pinned run (create) or the read, unchanged, with `at` verbatim on every query and
the stage's name in neither CTM nor bundle. `twin create --stage` never follows
(`dry_run.follow.reason: stage`). `--branch`, `--at` or `--interval` beside `--stage` is
`stage.flags.conflict` at `start`. The document carries `subject.stage` (as supplied) and
the `stage` block once resolved; `intent read`'s summary line begins `stage
change-1/cabled: …` where it began with the waypoint. The twin's closing line and `twin
show`'s kind line read `pinned at …, stage change-1/cabled; not following`.

### `twin step [--stage <branch>/<label>]`

The first lines:

```
twin: stage change-1/cabled (bundle f857d513…), pinned at …; 3 nodes
stage change-1/live: branch change-1 at … (given), "after its configuration is live"
step change-1/cabled → change-1/live (f857d513… → 7eafd93c…):
  …
```

The target: the next stage of the twin's proposed change in order when none is given
(the head when no mark follows); the one given otherwise, forward or back, the head
included when it has moved since the record. Refusals at `resolve`, before the from bundle,
the host check and containerlab's plan, each exit 1:

| Rule | When | Wording (shape) |
|---|---|---|
| `step.twin.unsteppable` | no twin; an orphan; an unreadable record; a record of `5` or earlier, or one naming no stage | `…; only a twin built from a stage steps (fylgja twin create --stage)`; `the twin was created from a waypoint of a record version this build no longer reads (twin.json 5); only a twin built from a stage steps; fylgja twin destroy clears it` |
| `step.target.foreign` | `--stage` names another branch, or another proposed change on the same branch (by id) | `stage other/x is not of proposed change <id> on branch change-1, the twin's; a step stays inside the proposed change the twin was built from, whose stages are: …` |
| `step.target.unknown` | no stage after the record's; the record's label gone; `--stage` names no stage of the proposed change | `proposed change <id> on change-1 has no stage after change-1/head; its stages are: …` / `…; the head has moved since the twin was built (now at …): --stage change-1/head steps to it` |
| `step.target.current` | the target resolves to the record's `(branch, at)` | `the twin is already at stage change-1/live (branch change-1, at …); the proposed change's stages are: …` |
| `step.stage.skipped` (warning) | marks strictly between the record's position and the target's | `the step from change-1/branch-point to change-1/head skips stages cabled, live; the step is between the two bundles either way` |
| `stage.twin.moved` (warning, no step) | the record's stage no longer resolves to the record's `(branch, at)`: the head written since, a mark's `as_of` edited, a rebase; filed once a target is chosen, as `stage list` files it, on the dry run and the run alike, and before the failure of a step that fails after its target | `the twin was built from stage change-1/head at branch change-1, at … (head); change-1/head now resolves to branch change-1, at … (head); the twin is pinned to what it was built from` |

The target's own resolution refusals (the reference contract's steps 4–9) follow, with the
same identifiers and wordings as `twin create --stage` gives. Everything after the target
(D-036's rules, the dry run, the run, the wait, the closing lines) is M11's and M12's with
"stage" for "waypoint": `stepped to stage change-1/live (bundle …) in 4.1s: …`;
`unchanged; the record moves to stage change-1/head (bundle …) in 0.9s`; `diverged towards
stage change-1/live (bundle …) at phase push: …; the twin is up at stage change-1/cabled
(bundle …); fylgja twin destroy clears it`. Once the target is chosen, every document the
step ends with carries the warnings found by then (`step.stage.skipped`,
`stage.twin.moved`, the target's `stage.main.moved`), each once: a refusal's, the dry run's
and the run's, and, ahead of its `operation.failed`, a failure's (the from bundle
unreadable, the host check, containerlab's plan, the run's start).

### `twin show`, `twin verify`, `schema check`

`twin show`'s kind line: `pinned at …, stage change-1/cabled; not following`, and after a
step `pinned at …, stage change-1/live (stepped from change-1/cabled by run fylgja-step
…, ended …); not following`; the `show` block's `record.stage` carries the `6` shape;
`in_flight` names `stepping towards stage change-1/live`. `twin verify`'s first line: `twin:
stage change-1/live (bundle …), ready, pinned at …; 3 nodes`; the `verify` block's
`twin.stage` and `diverged.towards.stage`. A record of `5` or earlier that stepped or
diverged names each stage of its step as the waypoint it was, `a waypoint of a record
version this build no longer reads (twin.json 5)`, never `none`, in those lines and in
`step.twin.diverged`; its JSON's stages stay `null`. `schema check`'s last line: `stages: FylgjaStage
present on the default branch, with its extension` / `stages: FylgjaStage absent from the
default branch (load schema/fylgja-stage.yaml; needed only by --stage, stage list and
stage plan)` / `stages: FylgjaStage on the default branch lacks description (load …)` /
`stages: FylgjaStage present on the default branch, but CoreProposedChange lacks
fylgja_stages (load …)`; `verified.stages` carries `kind`, `present`, `missing`,
`extension`, `file`.

## The API

| Operation | Path | `args` | Files in | Files out | Takes an interrupt |
|---|---|---|---|---|---|
| `twin.create` | `/v1/twin/create` | `branch`, `at`, `stage`, `interval`, `no_follow`, `dry_run` | | | from `start` |
| `twin.step` | `/v1/twin/step` | `stage`, `allow_restart`, `dry_run`, `wait` | | | from `start` |
| `stage.list` | `/v1/stage/list` | `branch` | | | no |
| `stage.plan` | `/v1/stage/plan` | `branch` | | | no |
| `intent.read` | `/v1/intent/read` | `branch`, `at`, `stage`, `out` | | the CTM | no |

`waypoint.list` and `waypoint.plan` are gone: `/v1/waypoint/list` is `404` as any path
that names no operation. A request carrying `waypoint` is `400`, `twin.create takes no
argument "waypoint"`. `api.Version` stays `"1"`; `api.schema.json`'s `args` definitions
move; `api.md`'s section "014: the stage surface" names the two operations removed, the two
added and the argument renamed, and says the version did not move because the API is
pre-1.0 and every other operation is unchanged.

## The findings document

`findings.schema.json` stays version `1`. Operations: `stage.list`, `stage.plan` for the
two removed. `subject.stage`: the reference as supplied (`^[^/\s]+/[^/\s]+$`); on
`twin.step`, the target once known. Blocks, each by `$id` in
[stages.schema.json](stages.schema.json): `stage` (`$defs/resolved`) on `twin.create`, its
dry run, `intent.read` and `twin.step` once resolved; `stages` (`$defs/list`) on
`stage.list`; `plan` (`$defs/plan`) on `stage.plan`. `verified.stages` on `schema.check`.
`dry_run.follow.reason` enum: `pinned`, `no_follow`, `bundle`, `stage`. The step enum,
statuses and exits are unchanged. `show.schema.json`'s `record.stage` and the step sides,
`step.schema.json`'s `$defs/stage` and `side.stage`, `verify.schema.json`'s `$defs/stage`,
`twin.stage` and `towards.stage` carry the `6` shape (`proposed_change {id, branch}`,
`label`, `description`, `at_source`). The frozen copies under `008-waypoints` go with their
tests; the current contracts are the record of the format.

## `twin.json` 6

`contracts/twin.schema.json`, `$id https://github.com/happypathnetworking/fylgja/contracts/twin/v6`, `twin_version`
`"6"`. `waypoint` is gone; `stage` is required, an object or `null`:

```json
"stage": {
  "proposed_change": {"id": "18df1273-…", "branch": "change-1"},
  "label": "cabled",
  "description": "after the link is cabled",
  "at_source": "written"
}
```

`at_source` is one of `given`, `written`, `branch_point`, `head`; `provenance.at` is the
`at` itself and `provenance.branch` the branch read (`main` for a branch-point twin). A
stage is recorded only on a pinned, intent-sourced record (the conditional that held
`waypoint` holds `stage`). `step.from.stage` and `step.to.stage` carry the same shape or
`null`; everything else of `5` stands. A create writes a `6` record with `step: null`.
The `5` schema is frozen under `internal/lab/testdata/contracts/010-verify/`, and a `5`
record reads with no stage (research R-11).

## Identifiers

The table in [research.md R-08](../research.md#r-08): twelve `stage.*` rules (seven for
the waypoint's, five new), `step.stage.skipped` for `step.sequence.skipped`, the three
`step.target.*` unchanged and reworded, `waypoint.time.reversed` dropped. Exit statuses:
`stage.ref.invalid` and `stage.flags.conflict` 2 at `start`; every other `stage.*`
rejection 1 at `resolve`; the warnings 0. No status, step or operation beyond the two is
new.
