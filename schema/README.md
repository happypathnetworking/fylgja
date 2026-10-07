# Schema

The generics contract Fylgja ships, and a reference concrete schema implementing it
for greenfield installs. See architecture [§4.1](../docs/architecture.md#41-intent-reader)
and [D-002](../docs/decisions.md#d-002).

| File | Purpose |
|---|---|
| `fylgja-generics.yaml` | The generics Fylgja queries, and the `FylgjaContract` kind that carries the contract's version. The generics are contract 0.1's; 0.2 adds that a kind implementing `FylgjaDevice` also inherits Infrahub's `CoreArtifactTarget` ([D-028](../docs/decisions.md#d-028)). The artifact of record. |
| `reference.yaml` | Concrete kinds implementing the generics. Adopt, extend, or replace. |
| `fylgja-waypoint.yaml` | The waypoint kind: a named mark for a pinned intent reference, which the operator writes and Fylgja only reads. Beside the contract, not in it (the contract stays 0.2); loaded on the default branch as the contract is (D-028); needed only by `--waypoint`, `waypoint list` and `waypoint plan`. |

The interface kind attribute is `iftype` ([D-003](../docs/decisions.md#d-003)): Infrahub
rejects `class` (Python keyword) and `type` (reserved). One caveat remains: Infrahub
reports `display_labels` as deprecated in favour of `display_label` — a cleanup, not an
error.

The contract's version is held by a `FylgjaContract` object on the branch, a singleton
whose kind `fylgja-generics.yaml` defines. Every read, and `fylgja schema check`, compares
it with the version the build understands, `0.2`, before anything else.

## Waypoints: writing one

A waypoint names a pinned intent reference — a branch and a point in time — so a twin can
be built from it by name (`fylgja twin create --waypoint demo/2`), and a series of them
listed and planned with no lab (`fylgja waypoint list`, `fylgja waypoint plan --series
demo`). The operator writes waypoints; Fylgja only reads them, from the default branch.

**Load the kind once**, on the default branch, beside the contract:
`infrahubctl schema load schema/fylgja-waypoint.yaml` (check it first with `infrahubctl
schema check`, as for the other files). `fylgja schema check --branch <b>` then says
`waypoints: FylgjaWaypoint present on the default branch`. An installation that never loads
it loses only the three waypoint commands, each refused naming this file.

**The fields.** A waypoint is named `<series>/<sequence>`, and the pair is unique.

| Field | Required | Meaning |
|---|---|---|
| `series` | yes | The series it belongs to: a name with no `/` and no whitespace. `fylgja-test-*` names belong to Fylgja's tests, which remove them. |
| `sequence` | yes | Its place in the series: a positive integer, written with no leading zero. |
| `branch` | yes | The branch it seals, by name: any branch, `main` included. The waypoint outlives the branch. |
| `as_of` | no | The reference's point in time, used verbatim (at most six fractional digits). One later than now is refused at resolution until it has passed. Left out, it is the moment the waypoint's `branch` was written. |
| `description` | no | What this chapter of the story is. |

**The attribute is `as_of`; Fylgja says `at`.** Infrahub refuses attribute names shorter
than three characters, so the kind cannot call it `at`. Every command, report and record
calls it `at`, and says where it came from: `(given)` when `as_of` was written, `(written)`
when it is the waypoint's own write time.

**Three ways to write one**, all Infrahub's own. An object file, loaded with
`infrahubctl object load waypoints.yml` (the kind is branch-agnostic, so any branch would
do; the default branch is the one that always has it):

```yaml
---
apiVersion: infrahub.app/v1
kind: Object
spec:
  kind: FylgjaWaypoint
  data:
    - series: demo
      sequence: 1
      branch: main
      description: before the change
    - series: demo
      sequence: 2
      branch: change-1
      description: after the first cut-over
    - series: demo
      sequence: 3
      branch: change-1
      as_of: "2026-09-28T16:00:00Z"
      description: after the second, at a chosen instant
```

Or the UI (Waypoint, under the Fylgja menu, with the fields above); or
`infrahubctl object create FylgjaWaypoint --set series=demo --set sequence=4 --set
branch=change-2 --set description="after the rollback"`.

**The one rule: write the waypoint last** — after the branch's writes, and after its
artifacts are generated and Ready. A waypoint with no `as_of` seals the branch as it was the
moment the waypoint was written; one written before the generate seals the old artifact. A
twin built from it then runs the old configuration, and `waypoint plan` shows a topology
step with no artifact change. Fylgja infers nothing from that; it reports what the waypoint
sealed.

**Editing a waypoint.** Changing `description` changes nothing Fylgja reads. Changing
`branch` moves an unwritten `at` to the moment of the change. A written `as_of` is what it
says. None of this changes a twin already built from the waypoint: the twin is pinned to
what it was built from, and `waypoint list` warns beside it (`waypoint.twin.moved`) when the
waypoint now resolves elsewhere or is gone.

**Stepping back.** One twin runs at a time. To move the twin to another waypoint of the
series, earlier or later, destroy it and create from the other:
`fylgja twin destroy`, then `fylgja twin create --waypoint demo/1`.
