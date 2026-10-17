# Data model: a proposed change's stages

**Feature**: `014-proposed-change-stages` · **Plan**: [plan.md](plan.md) · **Research**:
[research.md](research.md) (§5 decisions, §6 verified)

What moves: the kind on `main`, `twin.json` to `6`, the findings document's stage blocks
(`stages.schema.json`), the API's `stage` arguments and two operations, the fixture tool.
What does not: bundle `4`, CTM `1`, PSP `0.6`, contract `0.2`, findings `1`, the API `1`,
the three goldens, the fixture's `47b2c449…`, the four workflows and twenty activities
(FR-024). Each entity names the contract that fixes its wire form.

## 1. The kind: `FylgjaStage` and the extension

Contract: [contracts/stage-kind.md](contracts/stage-kind.md). File:
`schema/fylgja-stage.yaml`, embedded, loaded on `main` beside the contract (D-028).

| Property | Value | Why |
|---|---|---|
| kind | `FylgjaStage` (`namespace: Fylgja`, `name: Stage`, label `Stage`, icon `mdi:map-marker-path`) | the candidate's (research-probe) |
| `branch` | `agnostic` | a mark lands in no branch's diff; read from the default branch |
| `description` | "A marked moment of a proposed change: its source branch at a point in time." | ≤128 characters |
| `display_label` | `{{ label__value }}` | the UI's name for a stage |
| `order_by` | `[as_of__value]` | Infrahub's listing; Fylgja orders in memory by the resolved `at` |
| `uniqueness_constraints` | `[[proposed_change, label__value]]` | a label is unique within its proposed change; the relationship is mandatory and cardinality one, as a constraint requires |
| `human_friendly_id` | none | refused through the proposed change's non-unique name (research §2.2) |
| `include_in_menu`, `generate_profile` | `true`, `false` | the candidate's |
| attribute `label` | Text, required, `regex ^[^/\s]+$`, `order_weight 1000` | the stage's name in a reference; one shell word |
| attribute `as_of` | DateTime, optional, `order_weight 1100` | the reference's `at`, verbatim, at most six fractional digits; omitted, the mark's own write stamp |
| attribute `description` | Text, optional, `order_weight 1200` | prose; Fylgja prints it and reads nothing from it |
| relationship `proposed_change` | peer `CoreProposedChange`, kind Attribute, cardinality one, `optional: false`, identifier `proposed_change__fylgja_stages`, `order_weight 900` | the stage's home; its branch is the proposed change's source |
| extension on `CoreProposedChange` | `fylgja_stages`, peer `FylgjaStage`, kind Generic, cardinality many, optional, the same identifier | the proposed change lists its stages |

**Migration on `main`** (research §6.2): from the candidate already there, the diff is
`description` added and `label`'s description and regex changed; from a `main` that never
had the kind (CI's runner), the kind and the extension are added. **Removal**:
`migration/fylgja-waypoint-absent.yaml` (`state: absent`), idempotent (§6.3). `main`'s
schema hash moves with each; the fixture branch's does not.

**Validation at write** (Infrahub's, verified): a second stage with one label on one
proposed change is refused (`Violates uniqueness constraint 'proposed_change-label'`); a
label with `/` or whitespace is refused by the regex; `as_of` keeps what it is given and
refuses nonsense. Infrahub accepts a mark labelled `head` or `branch-point` (§6.4): Fylgja
refuses it at list and resolve.

## 2. The proposed change, as Fylgja reads it

Read through `intent.StageReader` on the default branch's unnamed endpoints (research
R-03), never written.

| Field | From | Used for |
|---|---|---|
| `id` | `CoreProposedChange.id` | the record's and the blocks' `proposed_change.id`; `step.target.foreign` |
| `name` | `name.value` | printed; never an identity (not unique) |
| `branch` | `source_branch.value` | how a proposed change is found: one open per branch |
| `destination` | `destination_branch.value` | printed in the plan's heading; always `main` in 1.11.2 |
| `state` | `state.value`: `open`, `closed`, `merged`, `canceled` | **visibility**: `open` alone is visible to Fylgja (FR-009), draft or not |
| `draft` | `is_draft.value` | printed; the list's `draft` field |
| `stages` | `fylgja_stages { edges { node { id label { value updated_at } as_of { value updated_at } description { value } } } }` | the marks (§3) |
| `validations` | `CoreArtifactValidator(proposed_change__ids:) { completed_at { value } }`, pinned at a stage's `at` | the generation stamp (§5) |
| the branch | `Branch(name:) { branched_from created_at }` | the branch point's `at`; the rebase rule |

**States and what Fylgja does**

```
                 open (draft or not)        closed / merged / canceled        deleted (once no stage names it)
stage list       listed, marked, warned      not listed                        not listed
stage plan       planned                     stage.unknown ("no open …")       stage.unknown
--stage          resolved                    stage.unknown                     stage.unknown
a twin's record  kept; stage.twin.moved when the stage no longer resolves to the record's reference, or is gone
```

Infrahub refuses a proposed change's delete while a stage names it (research §8.8). A
stage removed from its proposed change's `fylgja_stages` names none: `stage list` lists it
after the proposed changes with the warning `stage.orphaned`, and nothing plans it or
creates from it ([D-047](../../docs/decisions.md#d-047)).

A deleted source branch cancels its proposed change about 16 s later (§2.3); until then
its stages list and every read of them fails on the missing branch (`operation.failed`
naming the branch, as a deleted branch's read does today).

## 3. The stage

A pinned intent reference on the proposed change's source branch, one of three kinds.

| Kind | Reference | `branch` read | `at` | `at_source` | Written by |
|---|---|---|---|---|---|
| branch point | `<branch>/branch-point` | `main` | the branch's `branched_from`, verbatim | `branch_point` | derived |
| mark | `<branch>/<label>` | the source branch | `as_of` as written, else the mark's own write stamp (`label.updated_at`), verbatim | `given` / `written` | the operator |
| head | `<branch>/head` | the source branch | the latest stamp across the branch's intent and artifact checksums, plus one microsecond, in the stamp's layout (`…T15:04:05.000000+00:00`) | `head` | derived |

**Order** (FR-005): the branch point first, the marks by `at` (parsed; two equal `at`s by
label), the head last, whatever the marks' stamps; a mark whose `at` Go cannot parse sorts
after those it can, by its string, and makes no time claim.

**`Resolved`** (`stages.Resolved`; the `stage` block, `$defs/resolved`):

| Field | Meaning |
|---|---|
| `ref` | `<branch>/<label>` as the operator would write it |
| `branch` | the branch the read is on (`main` for the branch point) |
| `label` | the mark's label, or `branch-point` / `head` |
| `proposed_change` | `{id, name, branch, draft}` |
| `at`, `at_source` | §3's table |
| `description` | the mark's, or `""` |
| `id` | the mark's object id; `""` for a derived stage (not in the block) |

## 4. The stage reference

Contract: [contracts/stage-reference.md](contracts/stage-reference.md).

`<branch>/<label>`, split at the first `/`. Branch: `^[^/\s]+$`. Label: `^[^/\s]+$`, held
equal to the kind's regex by a test. Reserved labels: `branch-point`, `head`. Malformed:
`stage.ref.invalid`, exit 2, at `start`, before any connection. `stage list --branch` and
`stage plan --branch` take a branch under the same pattern, refused the same way.

**Resolution** (`stages.Resolve`), in order; the first refusal ends it, every one at step
`resolve`, exit 1 unless said, before any run and before any branch's intent is read (a
stamps query reads stamps, not intent):

1. the kind, the attributes this build reads and the extension, from the default branch's
   schema → `stage.kind.absent`, naming `schema/fylgja-stage.yaml`;
2. an open proposed change on the branch → `stage.unknown` ("no open proposed change has
   source branch b; the branches with one are: …");
3. the branch's `branched_from` and `created_at` → an unknown branch is `stage.unknown`;
4. the stage named: `branch-point`, `head`, or a mark by label → `stage.unknown` naming the
   proposed change's labels; two marks with one label → `stage.duplicate`; a mark labelled
   `head` or `branch-point` → `stage.label.reserved`;
5. the `at`: a mark with no `as_of` and no write stamp → `stage.at.unresolved`; more than
   six fractional digits → `intent.at.precision` (exit 2); a given `as_of` later than the
   server's clock → `stage.at.unresolved` (the clock is read once and never sent);
6. the head's `at` computed from the branch's unpinned stamps (§5);
7. an `at` before `branched_from` → `stage.at.before_branch_point`, saying a rebase did it
   when `created_at` is before the `at` (every mark at once after a rebase);
8. the staleness rule at the stage's `at` → `stage.artifact.stale`, one finding per device;
9. warnings that refuse nothing: `stage.main.moved` when `main`'s latest stamp is later than
   `branched_from`.

A listing (`stage list`) applies steps 1–6 and 9 and refuses nothing but the kind absent;
a reserved label is a rejection beside the row. A plan applies every step per stage and
goes on.

## 5. Stamps, the head and the staleness rule

Contract: [contracts/stage-reference.md](contracts/stage-reference.md) §"Stamps".
Research R-05, R-06, R-07.

**`Stamps`** (`(*intent.Client).Stamps`, one query on the client's branch at its `at`):

| Field | From |
|---|---|
| `Latest` | the latest `updated_at` over every device's attributes and edges (§R-07) and every artifact's `checksum.updated_at` |
| `Devices[name].Intent` | the latest over that device's own attributes, its edges, its interfaces' edges and attributes, their `link` and `parent` edges, and the `endpoints` edges of every link an interface of its ends |
| `Devices[name].Artifacts[artifact name].Checksum` | that artifact's `checksum.updated_at` |

**The head's `at`** = `Latest` of the unpinned read, parsed, plus one microsecond,
formatted `2006-01-02T15:04:05.000000-07:00`.

**The generation stamp** of a device at a stage = the later of its artifact's
`Checksum` (the artifact of its package's `config.artifact_name`, pinned at `at`) and the
proposed change's artifact validator's `completed_at` value (pinned at `at`; absent when
no validator has run). **Stale** when `Devices[name].Intent` is later than the generation
stamp. A device with no artifact at `at` is the read's `artifact.missing`, not stale. The
branch point is checked too (on `main`, trivially fresh where `main` holds no device).

**`stage.main.moved`**: `main`'s unpinned `Latest` later than `branched_from`.

All comparisons are between stamps Infrahub returned (RFC 3339, six digits, `+00:00` or
`Z`); the server's clock enters only the future rule on a given `as_of`.

## 6. The list, the plan, the target

Contracts: [contracts/stage-commands.md](contracts/stage-commands.md),
[contracts/stages.schema.json](contracts/stages.schema.json).

**`stages.ListResult`** (`$defs/list`): `branch` (the filter or `null`); `rows`, every
visible proposed change's stages in order, sorted by branch then order, each `Resolved`
plus `twin` (whether the record names it); `orphans`, stages their proposed change no
longer names (`id`, `label`, `at`, `at_source`; D-047), each also `stage.orphaned`;
`record`, the host's readable record's stage and reference (`$defs/record`: `ref`,
`proposed_change {id, branch}`, `label`, `branch`, `at`, `at_source`, `state`,
`towards`), or `null`.

**`stages.PlanResult`** (`$defs/plan`): `branch`, `proposed_change`, `stages` in order, each
`PlanStage` (`ref`, `label`, `description`, `at_source`; `branch`, `at` once resolved;
`bundle_id` or `null`; `read` counts or `null`; `findings`; status `compiled`, `refused`
or `failed` with the first rejection's rule), and `steps`, one fewer, each `step.Pair`
(`$defs/step`, unchanged but for its `from`/`to` refs).

**`stages.Target`** (research R-16): over the proposed change's ordered stages, the
record's position by label; the target given or next; `step.target.foreign`,
`step.target.unknown`, `step.target.current` (by resolved reference), `step.stage.skipped`.

## 7. The twin record: `twin.json` `6`

Contract: `contracts/twin.schema.json` `6` ([contracts/stage-commands.md](contracts/stage-commands.md)
§"twin.json 6"); the frozen `5` under `internal/lab/testdata/contracts/010-verify/`.

| Key | `5` | `6` |
|---|---|---|
| `twin_version` | `"5"` | `"6"` |
| `waypoint` | `{series, sequence, description, at_source}` or `null` | gone |
| `stage` | — | `{proposed_change: {id, branch}, label, description, at_source}` or `null`; recorded only on a pinned, intent-sourced record, `provenance.at` the `at` itself |
| `step.from.waypoint`, `step.to.waypoint` | the same shape or `null` | `step.from.stage`, `step.to.stage`, the `6` shape or `null` |
| `provenance.branch` | the branch read | the same: `main` for a twin at a branch point |

`wire.StageRef{ProposedChange{ID, Branch}, Label, Description, AtSource}` replaces
`wire.WaypointRef` on `RecordInput`, `TwinRecord` and `StepSide`; `provision.StageInput`
aliases it. `NewRecord` refuses a stage on a bundle-sourced or unpinned record as it
refused a waypoint; `NewStepRecord` holds the previous record's stage equal to the step's
`from` side. A record of `5` or earlier reads with `Stage` nil (research R-11).

## 8. The findings document

`findings.schema.json` `1`: operations `stage.list`, `stage.plan`; `subject.stage` (the
reference as supplied); blocks `stage` (`$defs/resolved`, on `twin.create` and its dry run,
`intent.read` with `--stage`, `twin.step` once the target resolved), `stages`
(`stage.list`), `plan` (`stage.plan`), each by `$id` in `stages.schema.json`;
`verified.stages` on `schema.check`: `{kind: "FylgjaStage", present, missing: [],
extension, file: "schema/fylgja-stage.yaml"}`; `dry_run.follow.reason` gains `stage` for
`waypoint`; the step enum is unchanged. `show.schema.json`, `step.schema.json` and
`verify.schema.json` carry `stage` where they carried `waypoint`, with the `6` shape.

## 9. The API

`api.schema.json`, `api.md` ([contracts/stage-commands.md](contracts/stage-commands.md)):

| Operation | Path | `args` |
|---|---|---|
| `twin.create` | `/v1/twin/create` | `branch`, `at`, `stage`, `interval`, `no_follow`, `dry_run` |
| `twin.step` | `/v1/twin/step` | `stage`, `allow_restart`, `dry_run`, `wait` |
| `stage.list` | `/v1/stage/list` | `branch` |
| `stage.plan` | `/v1/stage/plan` | `branch` |
| `intent.read` | `/v1/intent/read` | `branch`, `at`, `stage`, `out` |

Present and empty is `--stage=` or `--branch=`, refused as before. The API stays `1`.

## 10. The fixture tool and test support

Contract: [contracts/fixture-tool.md](contracts/fixture-tool.md). Entities: a test branch
(`fylgja-test-*`), its draft proposed change (one open at a time; closed ones kept until
`-delete`), its stages; the deletion order stages → proposed changes → branch; the waits
(validators `completed`; a run-check's `completed_at` moved; a rebase complete).
