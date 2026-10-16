# Research: a proposed change's stages

**Feature**: `014-proposed-change-stages` · **Brief**: [brief.md](brief.md) ·
**Written**: 2026-10-16, on the development host (Ubuntu 26.04.1, Infrahub 1.11.2), before
`specify`, from one session that ran the live verifications the brief's
[Left to the plan](brief.md#left-to-the-plan) owed and put three findings to the operator.
Every fact below says how it was verified, with the wall time (UTC) the answer carries;
the raw exchanges are in that session's scratchpad log and are not committed. Each fact
that holds is in [verified-facts.md](../../docs/verified-facts.md) with its date.

§1 holds what the operator decided on the findings, §2 what was verified, §3 what the
brief's design changes as a result, and §4 what stays owed.

---

## 1. Decisions, 2026-10-16

The session put three questions to the operator once the branch verifications were in.
Each was answered as recommended, and [D-045](../../docs/decisions.md#d-045) records them.

### R-01 The candidate kind is loaded on `main` now

**Decision**: the probe's candidate ([research-probe/fylgja-stage.yaml](research-probe/fylgja-stage.yaml))
is loaded on `main` today, not at implement. `main`'s schema hash moved `0aba31a5…` →
`e7386419…`; the fixture branch keeps `0aba31a5…` and compiles to `47b2c449…` as before
(§2.9). The plan's final kind (which adds the optional `description` the brief gives it)
lands as a further migration; removal, if the plan reshapes it, is `state: absent`.

**Rationale**: it verifies the one thing a branch cannot — the extension of a core kind
on the default branch, and that a branch made before the load cannot read the kind until
rebased — and CLAUDE.md's State put it before the plan.

### R-02 The head is pinned one microsecond after the branch's latest stamp

**Decision**: the head stage's `at` is the latest `updated_at` across the source branch's
intent and artifacts, **plus one microsecond** — the smallest increment Fylgja can send,
since it refuses more than six fractional digits (`intent.at.precision`). Constitution VI
is amended to say so (1.2.0): an `at` read from Infrahub, or the first instant after one,
is passed as the operator's would be; one composed from a clock of Fylgja's own is still
forbidden.

**Rationale**: a read pinned at exactly an attribute's `updated_at` sees the node but
not the value (§2.6), so the brief's "pinned at the latest stamp" would read a half-visible
write. **Alternatives**: the head unpinned, read live and recorded by `observed_at`
(rejected: the brief's reason stands — every stage pinned, so a twin from the head is
reproducible until the branch moves); the head as a mark the operator writes (rejected:
the ends are derived).

### R-03 The branch point is read on `main`, pinned at `branched_from`

**Decision**: the first stage, "the source branch at its branch point", is read on
**`main`** pinned at the branch's `branched_from`, never on the branch. For a fresh
branch the two reads are identical (§2.1); after a rebase only the read on `main` is the
branch point (§2.7).

**Rationale**: a rebase re-stamps the branch's whole content at the new `branched_from`
and discards its earlier history from pinned reads, so the branch at `branched_from` then
reads the branch's own changes, half-visible, and not the base. `main`'s writes never
share the instant, so no increment is needed. **Alternative**: read on the branch and
refuse after a rebase (rejected: a detection where a correct read exists).

---

## 2. Verified on 2026-10-16 (development host, Infrahub 1.11.2)

On a throwaway branch `fylgja-test-stage-verify` seeded with the three-node fixture by
`fylgja-fixture` (created 17:20:19.944511, `branched_from` 17:20:19.944651, 140 µs
later; artifacts first `Ready` at 17:21:04), with the candidate kind loaded on it (check
202, load 200, hash `0aba31a5…` → `17934826…`, `FylgjaStageCreate` queryable 2 s later),
a draft proposed change `18df1273…` on it, and two further throwaway branches and proposed
changes where one was not enough. Everything was deleted after (§2.10).

### 2.1 A read pinned at exactly `branched_from`, and before it

The decision log's open question since D-012. On the branch, pinned at `branched_from`
exactly, at its `created_at`, one second before, and one hour before: the same answer
each time — `NetworkDevice 0, NetworkLink 0, FylgjaContract 0, CoreStandardGroup 1,
CoreArtifactDefinition 1, CoreReadOnlyRepository 1` — which is `main` as it then stood.
The same on `fylgja-fixture` at its own `branched_from` (2026-10-08T05:47:52.538186Z):
`main`'s group present; and at `main`'s own `branched_from` (05:43:47.307246): the group
absent, since it was made at 05:46:40. So a pinned read reaches back through the branch
point into `main`'s history, down to the default branch's creation. **Before that it is
refused**: `Requested time '2026-10-08T05:00:00.000000Z' is before branch 'main' was
created at '2026-10-08T05:43:47.306680Z'`, HTTP 200 with `http_status: 422` in the
extensions, on any branch and on `main`.

`Branch` carries `branched_from`, `created_at`, `origin_branch`, `status`,
`sync_with_git`, `is_default` and `schema_differs_from_default_branch`; nothing else.

### 2.2 The uniqueness constraint, the names, and the reverse relationship

- A second `FylgjaStage` with the same `label` on the same proposed change is refused:
  `Violates uniqueness constraint 'proposed_change-label'`, HTTP 200 with `http_status:
  422`, from the branch. The same label on another proposed change is accepted.
- Two proposed changes may carry one `name` (`fylgja-test-stage-verify` twice, on two
  source branches), which is why a human-friendly id through the proposed change was
  refused in the brief's probe.
- A proposed change's stages read both ways: `CoreProposedChange { fylgja_stages { count
  edges … } }` listed the three; `FylgjaStage(proposed_change__ids: [id])` and
  `FylgjaStage(proposed_change__source_branch__value: "<branch>")` filter to them (every
  attribute of the peer is a filter: `proposed_change__state__value` among them). The
  kind's default order (`order_by: [as_of__value]`) lists a stage with a written `as_of`
  first and the unwritten ones after, in write order.
- A stage's write stamps every attribute and the relationship edge alike: `label`,
  `as_of` (`null`) and `proposed_change.properties` all read `17:29:54.838969` for the
  stale mark. An unwritten `as_of` is read as its own `updated_at`, as a waypoint's
  `branch` was.
- From a branch whose schema lacks the kind — `main` before the load, `fylgja-fixture`,
  a branch created before the load — both `FylgjaStage` and the extension's field are
  unqueryable: `Cannot query field 'fylgja_stages' on type 'CoreProposedChange'` and
  `Cannot query field 'FylgjaStage' on type 'Query'`, HTTP 200 with a 500 in the
  extensions, as the waypoint kind was.

### 2.3 One open proposed change per source branch, and its life

- A second proposed change on a branch with an open one is refused: `An open proposed
  change already exists for branch '<branch>'` (422). So a proposed change is found by its
  source branch, and `stage list` needs no id form.
- `main` as source is refused: `The source and destination branch can't be the same`; a
  source that does not exist: `The specified source branch for this proposed change was
  not found`. A destination other than `main` was not reached (the open-proposed-change
  refusal came first).
- Created `state: open` whether or not `is_draft`. `CoreProposedChangeUpdate` with
  `state: closed` closes it; a new proposed change on the same branch is then accepted,
  and the closed one's stages still read through it (count 1 after the close).
- **Deleting the source branch cancels its open proposed change, asynchronously**: the
  `BranchDelete` returned after 8 s, the proposed change still read `open` 2 s later and
  `canceled` 16 s after the call (`state.updated_at` 17:36:51.28 for a delete called at
  17:36:35.15). A canceled proposed change names a branch that no longer exists.
- **`CoreProposedChangeDelete` succeeds under a stage that points at it**, and leaves
  the stage with `proposed_change { node: null }` despite `optional: false` and
  `cardinality: one`. A second delete of the same id is `NODE_NOT_FOUND` (404 in the
  extensions). So a test deletes a proposed change's stages before the proposed change.

### 2.4 The proposed change's pipeline, and when it generates artifacts

Watched as the artifacts' `checksum.updated_at` and the proposed change's `validations`:

| Trigger | Regenerated? | Timing |
|---|---|---|
| **Creation of a draft** (`is_draft: true`), with intent changed 1 s before | **yes** | `Data Integrity` concluded 22 s after the create, `Schema Integrity` 58 s, `Artifact Validator: srlinux_device_config` 64 s; the checksums moved at 59 s, every validator `completed`/`success` |
| An intent change on the branch while the draft is open | no | nothing in 100 s |
| `CoreProposedChangeRunCheck(data: {id, check_type: ARTIFACT})` after an intent change | **yes** | `Data Integrity` re-ran (13 s), the artifact validator `in_progress` at 21 s, checksums moved at 22–25 s, `completed` at 26 s |
| `is_draft` → `false` after an intent change | no | nothing in 100 s |

So the pipeline runs at the proposed change's creation, draft or not, and on a
run-check; a branch update and the end of a draft start nothing. The brief's staleness
finding therefore fires for a stage marked after an intent change that followed the last
creation, run-check or hand generate — exactly the case the draft workflow invites, since
the operator builds the change on an open draft. `CheckType` is `ARTIFACT, DATA,
GENERATOR, REPOSITORY, SCHEMA, TEST, USER, ALL`.

### 2.5 An artifact's stamp at a pinned read, and the staleness rule

- A first generation stamps `checksum`, `storage_id` and `status` alike (17:21:04.315126
  for n1). **A regeneration moves `checksum.updated_at` and `storage_id.updated_at`
  together and leaves `status.updated_at` where it was** (`Ready` → `Ready` is no change:
  17:21:04 throughout four regenerations). So the artifact's stamp is the checksum's, and
  `ArtifactsReadyAt`'s reading of the status stamp sees only the first generation.
- A pinned read returns the stamps of the versions in force at `at`, not the current
  ones: pinned at 17:26:00, the checksum read `d902e9d1… @ 17:25:23` while the head read
  `35b1638c… @ 17:30:04`.
- **The rule holds in Infrahub's own stamps.** Intent changed at 17:27:31, a stage marked
  at 17:29:54 with no generate between, a generate at 17:30:04 (the checksums moved 7 s
  after the call), a stage marked at 17:30:06. Pinned at the first stage's stamp:
  `role.updated_at 17:27:31` > `checksum.updated_at 17:25:23`, stale. At the second:
  `17:30:04` > `17:27:31`, fresh. At 17:24:24.2 (intent changed, the pipeline not yet
  run): stale; at 17:26:00 (the pipeline run): fresh.

### 2.6 A pinned read at exactly a stamp sees the node and not the value

On `fylgja-fixture`, n1's `name.updated_at` is `2026-10-08T05:47:58.232738`. Pinned at
exactly that: `count 1`, every attribute `null`. One microsecond later: the values. One
microsecond earlier: no node. One **nanosecond** later (`…232738001`, nine digits, which
Infrahub takes and Fylgja refuses): the values. So the boundary is a strict comparison on
the attribute's own stamp, not a truncated stamp; the node's `created_at` is inclusive.
The same for an artifact: pinned at exactly n1's `checksum.updated_at`, n1's checksum
reads the **previous** version's (stamped 8 s earlier) while n2's, stamped 100 µs
before `at`, reads the current one.

Consequence (R-02): an `at` that must see a write is strictly after the write's stamp.
The stage with no `as_of` is safe as it was for waypoints, since its own write is after the
writes it seals; the head is not, and takes the microsecond.

### 2.7 A rebase re-stamps the branch and discards its history from pinned reads

`BranchRebase(data: {name}, wait_until_completion: true)` returned after 67 s.
`branched_from` moved to the rebase's moment (17:37:22.940060); `created_at` did not.
After it:

- every attribute at the head reads `updated_at 17:37:22.940060` — roles, checksums,
  all of them — and the diff tree's `from_time` is the new `branched_from`;
- pinned at any instant before it on the branch (the two stages' stamps, 17:35:00,
  17:37:22.939), **`NetworkDevice 0, CoreArtifact 0`**, where the same reads gave three
  of each before the rebase; `main`'s objects (the group) still read, and the stages,
  branch-agnostic, still count at their own stamps;
- pinned at exactly the new `branched_from`: three devices with every value `null`
  (§2.6); one microsecond later: everything, with the branch's own values (`stage-r4`),
  not `main`'s;
- `schema_differs_from_default_branch` read `true` after (the branch held the kind,
  `main` not yet).

So after a rebase the branch's pre-rebase history is unreadable, every stage marked
before it falls before the branch point, and the branch at `branched_from` is the
branch's content and not the base (R-03). `main` pinned at `branched_from` is the base
by definition, and `main` was not written at that instant.

### 2.8 How "behind `main`" is read, and the diff tree

- `DiffTreeSummary(branch)` and `DiffTree(branch)` exist, with `base_branch`,
  `from_time` (= `branched_from`), `to_time`, `num_added/updated/removed/conflicts`,
  `num_untracked_base_changes`, `num_untracked_diff_changes`, and nodes with
  `last_changed_at`. **The diff is a cached calculation**: after the run-check its
  `to_time` stayed at the run-check's moment while four intent writes and a regenerate
  went by (`num_untracked_diff_changes: 6`, the nodes' `last_changed_at` unmoved), and a
  `DiffUpdate` mutation (`branch, name, from_time, to_time`) refreshes it. So neither the
  head's stamp nor `main`'s movement is read from it without a mutation.
- `main`'s movement is therefore read as the head is: the latest `updated_at` across
  `main`'s intent and artifacts, compared with `branched_from`. It was not exercised by a
  write on `main` (the rules keep intent writes off `main`); the mechanism is the one
  §2.5 and §2.6 verify on the branch.
- Relationship edges carry their own stamp: `interfaces { edges { properties {
  updated_at } } }`, `device { properties { updated_at } }`, `endpoints { edges {
  properties { updated_at } } }`, so a re-cabling that writes no attribute still moves a
  stamp the head's read sees. `NetworkLink` has no `name`: its fields are `id`, `hfid`,
  `display_label`, `endpoints` and the groups.
- Infrahub returns no instant of its own: `InfrahubInfo` is `version` and
  `deployment_id`; HTTP's `Date` is whole seconds.

### 2.9 The kind and the extension on `main`

`POST /api/schema/check?branch=main`: 202, the diff adding `FylgjaStage` and the
relationship `fylgja_stages` on `CoreProposedChange`, no warning. `schema/load`: 200,
`previous_hash 0aba31a5…`, `hash e7386419…`, `schema_updated: true`;
`FylgjaStageCreate` queryable on `main` 2 s later. After it:

- `fylgja-fixture`'s hash stayed `0aba31a5…`, its `schema_differs_from_default_branch`
  flipped to `true`, and it still cannot query the kind; `fylgja intent read --branch
  fylgja-fixture` then `twin compile` through the server gave **`47b2c449…`**, the id
  before the load.
- The throwaway branch holding the same candidate kept its hash `17934826…`, so two
  branches with the same schema content hash differently: the hash is the branch's, not
  the content's.
- From `main`: `FylgjaStage { count }` 3, the proposed change's `fylgja_stages` 3,
  `FylgjaWaypoint` 0. A branch created after the load carries `main`'s hash and reads
  them; one created before does not.

### 2.10 Cleanup

The stages (deleted from `main`, where they now read), then the proposed change, then
the branch. After: `Branch` is `main` and `fylgja-fixture`; `CoreProposedChange 0`,
`FylgjaStage 0`, `FylgjaWaypoint 0`. The two other throwaway branches and their proposed
changes went the same way during the session.

---

## 3. What this changes in the brief's design

- **The head's `at` is the latest stamp plus one microsecond** (R-02), and Constitution
  VI is amended for it (1.2.0, citing D-045).
- **The branch point is read on `main` at `branched_from`** (R-03). The stage is still
  named as the branch's first; its read is `main`'s.
- **The artifact's stamp is `checksum.updated_at`**, never `status.updated_at` (§2.5).
  The staleness check compares it with the latest intent stamp, attributes and
  relationship edges both.
- **The pipeline regenerates at creation and on a run-check, draft or not** (§2.4), so
  the stale finding names the remedy as a regenerate or a run-check.
- **A rebase refuses every mark at once** (§2.7), as the brief said; the refusal can say
  the rebase did it when `branched_from` is later than the stage's stamp and the branch's
  `created_at` is not.
- **A proposed change deletes under its stages** (§2.3): tier 2 and tier 3 delete stages
  first, then the proposed change, then the branch; a stage with no proposed change
  (`proposed_change__isnull`) is a finding, not a crash.
- **A deleted branch's proposed change is canceled**, ~16 s later, and still names the
  branch (§2.3): `stage list` for a branch finds at most one open proposed change and
  may find canceled or closed ones, for clarify's question 2.
- **Fylgja still mutates nothing**: the diff tree would need `DiffUpdate`, so the head
  and `main`'s movement are read from stamps (§2.8).

## 4. Owed

- **Nothing before `specify`.** Every verification the brief listed is in §2.
- At implement, the final kind's load on `main` (a migration from the candidate), and
  the SDL refetched (`make sdl`) once it is.
- A write on `main` was not made to exercise "behind `main`" directly (§2.8); the
  comparison is the head's mechanism, verified on the branch. If a feature needs it
  exercised, a throwaway `CoreStandardGroup` on `main`, deleted after, is the cheapest
  write.
- The upstream request for named points in time, once the pass works (the brief's
  [Left to the plan](brief.md#left-to-the-plan)); §2.6 and §2.7 are worth a line in it.
