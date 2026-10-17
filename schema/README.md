# Schema

The generics contract Fylgja ships, and a reference concrete schema implementing it
for greenfield installs. See architecture [§4.1](../docs/architecture.md#41-intent-reader)
and [D-002](../docs/decisions.md#d-002).

| File | Purpose |
|---|---|
| `fylgja-generics.yaml` | The generics Fylgja queries, and the `FylgjaContract` kind that carries the contract's version. The generics are contract 0.1's; 0.2 adds that a kind implementing `FylgjaDevice` also inherits Infrahub's `CoreArtifactTarget` ([D-028](../docs/decisions.md#d-028)). The artifact of record. |
| `reference.yaml` | Concrete kinds implementing the generics. Adopt, extend, or replace. |
| `fylgja-stage.yaml` | The stage kind: a marked moment of a proposed change, which the operator writes and Fylgja only reads, and its extension of Infrahub's `CoreProposedChange` (`fylgja_stages`). Beside the contract, not in it (the contract stays 0.2); loaded on the default branch as the contract is (D-028); needed only by `--stage`, `stage list` and `stage plan` ([D-045](../docs/decisions.md#d-045)). |

The interface kind attribute is `iftype` ([D-003](../docs/decisions.md#d-003)): Infrahub
rejects `class` (Python keyword) and `type` (reserved). One caveat remains: Infrahub
reports `display_labels` as deprecated in favour of `display_label` — a cleanup, not an
error.

The contract's version is held by a `FylgjaContract` object on the branch, a singleton
whose kind `fylgja-generics.yaml` defines. Every read, and `fylgja schema check`, compares
it with the version the build understands, `0.2`, before anything else.

## Stages: marking one

A stage is a moment of a proposed change: its source branch at a point in time, named
`<branch>/<label>`, so a twin can be built from it (`fylgja twin create --stage
change-1/cabled`) and stepped to it (`fylgja twin step --stage change-1/cut-over`), and a
proposed change's stages listed and planned with no lab (`fylgja stage list`, `fylgja stage
plan --branch change-1`). Every proposed change has two stages of its own, derived and
never written: its **branch point** (`<branch>/branch-point`, the destination as it was
when the branch was made) and its **head** (`<branch>/head`, the branch as it is now). The
operator marks the moments between, each after that moment's writes and after its
artifacts are regenerated. Fylgja only reads stages, from the default branch.

**Open the proposed change first**, as a draft while the change is built, from the branch
being built: the UI's "Create proposed change" with the draft toggle on, or
`CoreProposedChangeCreate` with `is_draft: true`. `main` cannot be a source, and a branch
has at most one open proposed change. Its creation runs its checks, which render the
branch's artifacts.

**When to mark**: after the moment's writes have landed and its artifacts have been
regenerated, by the proposed change's checks (its creation, or a retry, runs the artifact
validator) or by a generate. A regenerated artifact lands a few seconds after the generate
returns: wait for its checksum to move. A stage marked before that is refused as stale
(`stage.artifact.stale`), naming each device and both remedies; mark it again after
regenerating. Leave `as_of` out unless an instant is wanted: the mark's own write is always
after what it seals, while a read pinned at exactly a stamp sees the node and not the
value.

**The fields.**

| Field | Required | Meaning |
|---|---|---|
| `label` | yes | What this moment of the change is: a name with no `/` and no whitespace, unique within its proposed change. `branch-point` and `head` name the two derived stages, and a mark so labelled is refused (`stage.label.reserved`). |
| `proposed_change` | yes | The proposed change it belongs to, by id. The stage's branch is the proposed change's source. |
| `as_of` | no | The point in time on the branch, used verbatim (at most six fractional digits). One later than now is refused (`stage.at.unresolved`) until it has passed; one before the branch point is refused (`stage.at.before_branch_point`). Left out, it is the moment the stage was written. |
| `description` | no | What this moment of the change is, in a sentence. |

**The attribute is `as_of`; Fylgja says `at`.** Infrahub refuses attribute names shorter
than three characters, so the kind cannot call it `at`. Every command, report and record
calls it `at`, and says where it came from: `(given)` when `as_of` was written, `(written)`
when it is the stage's own write time, and `(branch point)` and `(head)` for the two
derived stages.

**Three ways to write one**, all Infrahub's own. Neither the stage kind nor Infrahub's
proposed change has a human-friendly id, so a stage names its proposed change by id;
`fylgja stage list --branch <b>` prints it beside the proposed change's name. An object
file, loaded with `infrahubctl object load stages.yml` on the default branch, which always
has the kind (the kind is branch-agnostic, so a stage lands in no branch's diff):

```yaml
---
apiVersion: infrahub.app/v1
kind: Object
spec:
  kind: FylgjaStage
  data:
    - label: cabled
      proposed_change: 18df3629-86a6-8afb-33bf-c518dfa7f7ce
      description: the new links cabled
    - label: cut-over
      proposed_change: 18df3629-86a6-8afb-33bf-c518dfa7f7ce
      as_of: "2026-10-17T04:19:35Z"
      description: traffic moved, at a chosen instant
```

Or the UI: **Stage**, an entry of its own in the sidebar's object menu
(`/objects/FylgjaStage`), with the fields above and the proposed change chosen from its
list. Or `infrahubctl object create FylgjaStage --set label=verified --set
proposed_change=<id> --set description="checked by hand"`. To delete one: the UI,
`infrahubctl object delete FylgjaStage <stage id> --yes`, or `FylgjaStageDelete`.

**Editing a stage.** Changing `description` changes nothing Fylgja reads: the stage keeps
its `at`. Changing `as_of` moves the stage's `at`. Changing `label` renames its reference,
and on a stage with no `as_of` it moves the `at` too: that `at` is the label's own write,
so a relabelled stage names the moment of the relabel. To keep its moment, write that `at`
(as `stage list` shows it) as its `as_of` first. None of this changes a twin already built
from the stage: the twin's record keeps what it was built from, and `stage list` warns
beside it (`stage.twin.moved`) when the stage now resolves elsewhere or is gone, as `twin
step` does beside its target; the step still goes from the bundle the twin was built from.

**Delete stages before their proposed change.** Infrahub refuses a proposed change's
delete while a stage names it (`It is linked to mandatory relationship proposed_change on
node FylgjaStage …`). A stage removed from its proposed change's `fylgja_stages` is left
naming none: `stage list` reports each such stage as `stage.orphaned` until it is deleted
by id, and `stage plan` plans none of them. A branch deleted under an open proposed change
cancels it, about 16 seconds later.

**The kind on the default branch.** Load it once, beside the contract:
`scripts/bring-up.sh` does with the rest of `schema/`, or `infrahubctl schema load
schema/fylgja-stage.yaml` (check it first with `infrahubctl schema check`, as for the other
files). `fylgja schema check --branch <b>` then says `stages: FylgjaStage present on the
default branch, with its extension`. An installation that never loads it loses only the
stage surface: `--stage`, `stage list` and `stage plan` are each refused naming this file
(`stage.kind.absent`).

[A stepping twin](../README.md#a-stepping-twin) walks a twin through a proposed change's
stages, forward and back.
