# Contract: the fixture tool and test support for proposed changes and stages

Test tooling under the `fixture` and `contract` build tags; the one binary that writes to
Infrahub ([D-001](../../../docs/decisions.md#d-001)). Reads `INFRAHUB_ADDRESS` and
`INFRAHUB_API_TOKEN` from the environment, as every flag of the tool does. Replaces the
waypoint series ([research.md R-12](../research.md#r-12)).

## The fixture tool

```
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -propose                       # a draft proposed change on b; waits for its validators; prints the id
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -stage <label> [-at <t>] [-description <s>]
                                                                                   # marks one stage on b's open proposed change; prints its id and at
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -run-check                     # asks the open proposed change's ARTIFACT run-check; waits for the validator to complete
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -close                         # closes b's open proposed change (its stages stay)
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -delete                        # every stage of every proposed change whose source is b, then the proposed changes, then b
```

- **Guards, before any request**: every flag above refuses `fylgja-fixture` ("the fixture
  has no proposed change"; `-delete` alone keeps it, which `make infrahub-clean` deletes and
  which holds no proposed change) and a `-branch` that does not begin `fylgja-test-`
  (`testsupport.TestBranchPrefix`); `-at` and `-description` without `-stage` are refused as
  before; `-stage` with a reserved label (`head`, `branch-point`) is **not** refused, so a
  test can write what Fylgja must refuse; `-propose` on a branch with an open proposed change
  is Infrahub's refusal, printed.
- **`-propose`** creates `CoreProposedChange` with `name` the branch's, `source_branch` the
  branch, `destination_branch main`, `is_draft true`, then polls its `validations` every 2 s
  until it has one, every validator is `completed`, and, when the branch's devices render,
  its artifact validator is among them, or 180 s pass (about 9–17 s on a bare branch, 38–41 s
  on a seeded one; the validators appear one after another, so "every one completed" alone
  ends early, [research.md §8.6](../research.md)), and prints `proposed change <id> opened on <b>, draft; <n> validators
  concluded in <s>s`. The wait is what makes a following intent change safe from the
  creation's regenerate.
- **`-stage`** finds the open proposed change by `source_branch` and `state open`, writes
  `FylgjaStage` with `label`, `proposed_change {id}`, `as_of` when `-at` is given and
  `description` when given, on the default branch's GraphQL (the kind is agnostic), and
  prints `stage <b>/<label> marked on proposed change <id> (stage id …) at <stamp>
  (written|given)`.
- **`-run-check`** sends `CoreProposedChangeRunCheck(data: {id, check_type: ARTIFACT})`,
  then polls `CoreArtifactValidator(proposed_change__ids:)` every 2 s until a validator's
  `completed_at` value is later than it was before the call, or 120 s pass (about 21 s), and
  prints the new stamp.
- **`-close`** sends `CoreProposedChangeUpdate(data: {id, state: {value: "closed"}})`.
- **`-delete`** reads every proposed change whose `source_branch` is the branch, in every
  state; deletes each one's stages (`FylgjaStageDelete`), then each proposed change
  (`CoreProposedChangeDelete`), then the branch; prints the counts (`deleted 2 stages, 1
  proposed change, branch <b>`). A branch deleted under an open proposed change would
  leave it canceled and still naming the branch, so the order is fixed.
- **Removed**: `-waypoint`, `-delete-series`. `-at` and `-description` stay, for `-stage`.
- **Unchanged**: `-schema-only`, `-sdl`, `-add-link`, `-add-mixed-link`, `-generate`,
  `-set-role`, `-set-site`, `-disable-port`, `-mixed`, `-prepare-main` and its flags. The
  seed is one call, as before.

## Composing a story for a test

```
fixture -branch $B                              # seed (or -mixed)
fixture -branch $B -propose                     # the draft; waits for the pipeline
fixture -branch $B -stage seeded -description seeded
fixture -branch $B -add-link                    # writes and renders; wait for n1's and n3's checksums to move (e2e: await_checksums_moved)
fixture -branch $B -stage third-link -description "third link"
fylgja stage plan --branch $B                   # branch-point refused (contract.node.missing on this install), seeded, third-link, head
…
fixture -branch $B -delete
```

A stale stage for tier 2: `-set-role x` (an intent change, no generate), `-stage stale`,
then `stage plan` refuses it `stage.artifact.stale` naming n1, n2 and n3; `-generate` then
`-stage fresh` is planned; or `-run-check` instead of `-generate` (the validator's
completion counts as the generation). A non-rendered change for the hole R-05 closes:
`-set-site y`, `-stage site`, refused stale; `-generate` moves nothing; `-run-check`, then
`-stage site2` is planned.

## Test support (`internal/testsupport`, build tag `contract || fixture`)

`proposed.go` replaces `waypoints.go`:

| Helper | Does |
|---|---|
| `TestBranchPrefix = "fylgja-test-"`; `testBranch(name) error` | refuses any other branch before a request; every helper below calls it, but `StagesPresent`, `BranchExists` and `ArtifactsReadyAt`, which write nothing and need no guard |
| `OpenProposedChange(branch string, draft bool) (id string, err error)` | the create and the validators' wait (180 s) |
| `AwaitValidators(id string, timeout time.Duration) error` | every validator `completed` |
| `ValidatorsOf(id string) ([]ValidatorRow, error)` | `{ID, Label, State, Conclusion, CompletedAt}`, a proposed change's validators: one on a bare branch, three on a seeded one (research §6.4, §6.5) |
| `MarkStage(id, label, at, description string) (stageID, stamp string, err error)` | the write; returns `label.updated_at` |
| `UpdateStage(id string, fields map[string]any) error` | the stage's attributes on the default branch, each field (`label`, `as_of`, `description`) written as its value, a nil value clearing it; its proposed change is read first and must be a test branch's, as `MarkStage` checks it, and an orphan, which names none, is refused (T075) |
| `StagesOf(id string) ([]StageRow, error)` | `{ID, Label, At *string, WrittenAt, Description}` through `fylgja_stages` |
| `StagesPresent(ids []string) ([]string, error)` | which of the ids still read as stages on the default branch, whatever proposed change they name or none; writes nothing (T058) |
| `DeleteStagesOf(id string) (int, error)` | each stage |
| `ProposedChangesOf(branch string) ([]ProposedChangeRow, error)` | `{ID, Name, State, Draft}`, every state |
| `CloseProposedChange(id string) error` | `state closed` |
| `DeleteProposedChange(id string) error` | after its stages |
| `RunCheck(id string, timeout time.Duration) (completedAt string, err error)` | `ARTIFACT`; waits for `completed_at` to move (120 s) |
| `Rebase(branch string) error` | `BranchRebase(data: {name}, wait_until_completion: true)`, bounded 180 s (about 67 s) |
| `DeleteTestBranch(branch string) error` | stages, proposed changes, branch, in order |
| `DeleteTestBranchCounting(branch string) (stages, proposed int, err error)` | `DeleteTestBranch`'s order, returning how many stages and proposed changes went (T058) |
| `BranchExists(name string) (bool, error)` (`infrahub.go`) | whether Infrahub lists the branch by name; writes nothing (T058) |
| `ArtifactsReadyAt(branch)` (existing) | reads `checksum.updated_at`, not `status.updated_at` (research §2.5); the seed's wait is unchanged |

The contract tier's invariant after `make test-contract`: `Branch` is `main` and
`fylgja-fixture`, `CoreProposedChange { count }` 0, `FylgjaStage { count }` 0, and no
`FylgjaWaypoint` kind on `main` (`fylgja stage list` prints `no open proposed change`).
