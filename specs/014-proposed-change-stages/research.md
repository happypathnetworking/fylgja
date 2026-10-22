# Research: a proposed change's stages

**Feature**: `014-proposed-change-stages` · **Brief**: [brief.md](brief.md) ·
**Written**: 2026-10-16, on the development host (Ubuntu 26.04.1, Infrahub 1.11.2). §1–§4
before `specify`, from one session that ran the live verifications the brief's
[Left to the plan](brief.md#left-to-the-plan) owed and put three findings to the operator;
§5–§7 by `plan` the same day, after `specify`, from a second session that made the design's
decisions and verified what they rest on.
Every fact below says how it was verified, with the wall time (UTC) the answer carries;
the raw exchanges are in that session's scratchpad log and are not committed. Each fact
that holds is in [verified-facts.md](../../docs/verified-facts.md) with its date.

§1 holds what the operator decided on the findings, §2 what was verified, §3 what the
brief's design changes as a result, and §4 what the first session left owed. §5 holds the
plan's decisions (R-01…R-16), §6 what the plan verified, and §7 what is owed at implement.

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
  *Superseded by §8.8: this held with the kind on the branch alone. With the kind on
  `main`, Infrahub refuses the delete while a stage names it.*

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
  (`proposed_change__isnull`) is a finding, not a crash. *(§8.8: with the kind on `main`
  the delete is refused instead; an orphan arises when a stage is removed from its proposed
  change's `fylgja_stages`.)*
- **A deleted branch's proposed change is canceled**, ~16 s later, and still names the
  branch (§2.3): `stage list` for a branch finds at most one open proposed change and
  may find canceled or closed ones, for clarify's question 2.
- **Fylgja still mutates nothing**: the diff tree would need `DiffUpdate`, so the head
  and `main`'s movement are read from stamps (§2.8).

## 4. Owed, as the first session left it

Superseded by §7 where the two differ.

- **Nothing before `specify`.** Every verification the brief listed is in §2.
- At implement, the final kind's load on `main` (a migration from the candidate), and
  the SDL refetched (`make sdl`) once it is.
- A write on `main` was not made to exercise "behind `main`" directly (§2.8); the
  comparison is the head's mechanism, verified on the branch. If a feature needs it
  exercised, a throwaway `CoreStandardGroup` on `main`, deleted after, is the cheapest
  write.
- The upstream request for named points in time, once the pass works (the brief's
  [Left to the plan](brief.md#left-to-the-plan)); §2.6 and §2.7 are worth a line in it.

---

<a id="5-the-plans-decisions"></a>
## 5. The plan's decisions, 2026-10-16

Each names what was chosen, why, and what else was weighed. Where a decision touches the
text of [D-045](../../docs/decisions.md#d-045) it says so; one (R-05) needs an entry of its
own, which the operator writes or declines before the code it governs is built.

<a id="r-01"></a>
### R-01 The kind: the candidate plus `description` and a label rule, loaded as a migration

**Decision**: `schema/fylgja-stage.yaml` is the probe's candidate with two changes: the
optional `description` (Text, `order_weight` 1200) the brief gives it, and `label`
constrained by `parameters.regex: "^[^/\\s]+$"`, no `/` and no whitespace, as the
waypoint's `series` was, so that a stage reference is one shell word and splits at its
first `/` without ambiguity. The parser's `LabelPattern` is held equal to the kind's regex
by a test, as `waypoint.SeriesPattern` was. Everything else is the candidate's, so the
migration on `main` is the diff `schema check` printed (§6.2): `description` added,
`label`'s description and regex changed. The removal of `FylgjaWaypoint` is a separate
document, `migration/fylgja-waypoint-absent.yaml`, a node with `state: absent`, loaded once
by hand (§6.3). **Rationale**: the skill's migration rule (add optional fields; retire with
`state: absent`), and the two attributes the candidate lacked. **Alternatives**: a
human-friendly id through the proposed change (refused by Infrahub, §2.2); a `display_label`
through the proposed change's source branch so the UI's breadcrumb reads `branch/label`
(rendering unverified; deferred, §7); a label regex excluding the two reserved labels by a
negative lookahead (Infrahub's acceptance of lookaheads unverified, and the spec settled the
refusal at list and resolve); `order_by` on node metadata (the kind's `as_of` order is its
natural one, and Fylgja orders in memory whatever Infrahub does).

<a id="r-02"></a>
### R-02 The package is `internal/stages`

**Decision**: `internal/waypoint` is renamed `internal/stages`, package `stages`: `Ref`,
`Resolved`, `ProposedChange`, `Resolve`, `List`, `Plan`, `Build`, `Target`. **Rationale**:
`internal/stage` is the read-and-compile pipelines, so the singular is taken, and the module
already has a plural package (`findings`). **Alternatives**: `internal/change`,
`internal/proposed` (neither says what the package holds).

<a id="r-03"></a>
### R-03 The reader reads Infrahub's own kinds for the proposed change and the branch

**Decision**: `intent.StageReader` replaces `WaypointReader` on the default branch's
unnamed endpoints: `Check` reads `GET /api/schema` for `FylgjaStage` with `label`, `as_of`,
`description` and the relationship `proposed_change`, and for `CoreProposedChange`'s
`fylgja_stages`; `ProposedChanges(ctx, branch)` lists the open ones (`state__value:
"open"`, filtered by `source_branch__value` when a branch is named) with their stages
through `fylgja_stages`; `Orphans(ctx)` lists `FylgjaStage(proposed_change__isnull:
true)`; `Branch(ctx, name)` reads `Branch(name:)`'s `branched_from` and `created_at`;
`Validations(ctx, id, at)` reads `CoreArtifactValidator(proposed_change__ids:)`'s
`completed_at` pinned. `(*intent.Client).Stamps(ctx)` reads, on the client's branch at its
`at`, every stamp the read's selections carry (R-07). `readonly_test.go`'s root check
names `CoreProposedChange`, `CoreArtifactValidator` and `Branch` as the three roots that are
Infrahub's own and not the operator's model; every operation is still a query and the
concrete-kind check stands. **Rationale**: D-045 chose the proposed change as the stage's
home, and a branch's point of origin is the branch's to say; neither is a kind anyone
implements. **Alternative**: reading the branch point and the stages through a Fylgja
generic (there is none to read them through, and inventing one would reserve structure that
is a guess, Constitution III).

<a id="r-04"></a>
### R-04 An empty branch point is refused as any empty read is, and the plan goes on

**Decision**: the branch point is read on `main` at `branched_from` through the stage
pipeline like any stage, and on an install whose `main` holds no `FylgjaContract` object it
is refused `contract.node.missing` ("branch defines FylgjaContract but holds no instance
of it"), before a device is counted (§6.1). The plan prints `b/branch-point: refused
(contract.node.missing)`, the step to the first mark is `not_computed`, and the other stages
are planned; `twin create --stage b/branch-point` and a step to it are refused by the same
finding at `resolve`. Tier 2 and tier 3 assert that outcome on the development host, and a
twin is created from the first mark. **Rationale**: the development host's `main` carries
the schema, the group and the registration and no intent by design (the fixture is a
branch, and every test branch is seeded on itself), while a deployment's `main` carries the
network; the stage is a true reading of each. **Alternatives**: a contract object and
devices written on `main` for the tests (rejected: intent writes stay off `main`, and a
seeded `main` would collide with every throwaway branch's seed); a zero-device bundle for an
empty branch point (rejected: containerlab deploys no empty lab, and `ctm.devices.empty`
exists for this); the branch point left out of the list when `main` holds nothing (rejected:
its position is the design's, and the finding says why). **For the spec**: US1 scenario 1
and SC-004 say the two derived stages compile; on this install the branch point is refused
and the head compiles. `analyze` rewords them: "each resolved and planned; compiled where
`main` carries the contract and intent, which the development host's does not". **For
015**: a rehearsal's baseline on this install cannot be the branch point.

<a id="r-05"></a>
### R-05 The generation stamp is the later of the checksum's and the artifact validator's; staleness is per device

**Decision**: a device is stale at a stage when the latest stamp of its own intent, read
pinned at the stage's `at`, is later than its generation stamp, which is the later of its
artifact's `checksum.updated_at` (the artifact of its package's `config.artifact_name`,
read on the branch pinned at `at`) and the proposed change's artifact validator's
`completed_at` value (read on the default branch pinned at `at`). `stage.artifact.stale`
names the device and says to regenerate, by a generate or by the proposed change's checks,
and mark again. **Rationale**: §6.5 verified that a regeneration to identical bytes leaves
every checksum stamp where it was, on a generate and on a run-check alike, while the
run-check re-runs the proposed change's artifact validator (the same node) and moves its
`completed_at`. Under D-045's text, "intent newer than its artifact's checksum stamp", an
intent edit the template does not render (a device's `site`) would leave a stage stale with
no remedy that clears it, and 015's check would then fail a merge on a harmless edit; with
the validator's completion counted, the proposed change's checks always clear it, and a hand
generate clears it when the bytes change. Per device rather than branch-wide, because a
hand generate after a change leaves the unchanged devices' bytes identical and their
checksum stamps old: branch-wide, `-add-link` would make `n2` stale for ever after; per
device, exactly the devices whose intent moved are named (SC-003). The one case per device
misses, a neighbour's rename that changes this device's description line while none of its
own stamps moves, is covered by the run-check, which re-stamps the validator for every
device. **Alternatives**: D-045's rule as written (the hole above); branch-wide intent
(false positives after every hand generate); a warning instead of a refusal (contradicts
D-045 and D-045's reason); reading the artifact's node metadata for a generation stamp
(unverified whether an identical regeneration touches it; the validator is verified).
**This refines D-045's text**, which names "each artifact's `checksum.updated_at`" alone
and compares with "the latest intent stamp on the branch". The draft entry, for the
operator:

> **D-046 — A stage's generation stamp is the later of its artifact's checksum stamp and
> the proposed change's artifact validation; staleness is judged per device.** Refines
> [D-045](../../docs/decisions.md#d-045). A regeneration to identical bytes writes no checksum and no storage id,
> so an intent edit the template does not render would leave a stage stale under D-045's
> rule with no remedy that clears it; the proposed change's artifact validator is re-run on
> every run-check, identical bytes or not, and its `completed_at` moves (verified 2026-10-16
> on 1.11.2). A device is stale at a stage when the latest stamp of its own intent,
> attributes and relationship edges, pinned at the stage's `at`, is later than the later of
> its artifact's `checksum.updated_at` and the proposed change's artifact validator's
> `completed_at`, both pinned at `at`. The remedy names both ways to regenerate. Nothing
> else in D-045 moves.

`tasks` tagged the entry `[operator]` (T011); the operator accepted it at `analyze` on
2026-10-16, and it is [D-046](../../docs/decisions.md#d-046) in the decision log.
*Widened at T078 (2026-10-17, §8.19; [D-048](../../docs/decisions.md#d-048)):* a device's
intent was written at the later of the latest stamp of its own intent and the latest intent
event of the source branch's log that names it, by its id or one of its interfaces' ids as
read at the stage, no later than the stage's `at`; the generation stamp and the remedy are as
they were. As first written, the rule read the stamps alone, so a removal, which moves no
stamp (§8.17), left a stage marked after it fresh.

<a id="r-06"></a>
### R-06 The head's `at` is the latest stamp plus one microsecond, in the stamp's own layout

**Decision**: the head's `at` is computed from an unpinned `Stamps` read of the source
branch: the latest `updated_at` across every attribute and relationship edge the read
selects, on devices, interfaces and links, and every artifact's `checksum.updated_at`;
parsed (RFC 3339), plus one microsecond, formatted `2006-01-02T15:04:05.000000-07:00`, the
layout Infrahub's own stamps have (`2026-10-08T05:48:38.544482+00:00`), and passed
verbatim on every query of the head's read. The validator's completion is not a stamp of
the branch and does not enter the head's `at`. The same unpinned `Stamps` serves the head's
staleness check. **Rationale**: R-02 of §1 and Constitution VI 1.2.0; a read pinned at
exactly a stamp sees the node and not the value (§2.6). **Alternative**: the `Z` layout
Infrahub also accepts (rejected: the record's `at` should read as the stamps beside it do).
*Refined at T078 (2026-10-17, §8.19; [D-048](../../docs/decisions.md#d-048)):* the head is
one microsecond after the later of that latest stamp and the `occurred_at` of the source
branch's latest intent event, the events after the latest stamp alone read for it, in the
same layout. As first written, the head was the stamps' alone, and pinned before a removal
that no stamp records (§8.17).

<a id="r-07"></a>
### R-07 What a device's intent stamp is

**Decision**: a device's latest intent stamp is the latest of: its attributes' `updated_at`
(`name`, `role`, `site`), its `platform` edge's; each of its interfaces' edge, attributes
(`name`, `iftype`, `mgmt_only`, `enabled`), `link` edge and `parent` edge; and, for every
link an interface of its is an endpoint of, the link's `endpoints` edges. `addresses` are
read but not stamped (they do not reach the artifact or the bundle). An unset relationship's
`properties.updated_at` is `null` and is skipped (§6.6). One `Stamps` query selects them
all, spreading the artifact fragment `on CoreArtifactTarget` as the read does (a direct
`artifacts` on `FylgjaDevice` is refused, §6.6). **Rationale**: a re-cabling that writes no
attribute still moves an edge stamp (§2.8), and a link's endpoint edges name both devices.
*Corrected at T076 (2026-10-17, §8.16), by this decision's own criterion:* the platform's
`vendor`, `nos` and `version` are stamped too, each folded into the intent of every device
on the platform, since the template renders all three into each device's artifact and
branches on `nos`, and `nos` picks the package and enters the manifest; `model`, like
`addresses`, reaches neither and is read but not stamped. As first written, the decision
stamped the device's `platform` edge alone, so a platform edited on the branch after the
last regenerate moved no device's intent and no `Latest`. *At T078 (2026-10-17, §8.19):*
the same fields decide which of the branch's events are intent's (D-048): a node's creation
or deletion, or an update changing one of them; an update of a node's memberships or
artifacts alone, which Infrahub writes after every generation, is not.

<a id="r-08"></a>
### R-08 The identifiers

**Decision**: seven `waypoint.*` rules become `stage.*` ones, five are added, one is
dropped, and one M11 rule whose noun was the waypoint's is renamed: twelve `stage.*` rules. The step named `stage`
and the M2 rule `stage.failed` are the staging step's and are untouched; no new rule
collides with them.

| Was | Is | Why |
|---|---|---|
| `waypoint.ref.invalid` | `stage.ref.invalid` | `--stage`, or `--branch` on `stage list`/`stage plan`, malformed |
| `waypoint.flags.conflict` | `stage.flags.conflict` | `--stage` beside `--branch`, `--at` or `--interval` |
| `waypoint.kind.absent` | `stage.kind.absent` | the kind, an attribute of it, or the extension absent on the default branch |
| `waypoint.unknown` | `stage.unknown` | no open proposed change on the branch; no such stage of it |
| `waypoint.duplicate` | `stage.duplicate` | two marks of one proposed change share a label (a defence against the constraint, kept as before) |
| `waypoint.at.unresolved` | `stage.at.unresolved` | a given `as_of` later than now; a mark with no stamp at all |
| — | `stage.at.before_branch_point` | a stage's `at` before `branched_from`; says a rebase did it when `created_at` is before the `at` |
| — | `stage.label.reserved` | a mark labelled `head` or `branch-point` |
| — | `stage.artifact.stale` | R-05 |
| — | `stage.orphaned` (warning) | a stage its proposed change no longer names, removed from its `fylgja_stages` (D-047; first written as one whose proposed change was deleted under it, which §8.8 found Infrahub refuses) |
| — | `stage.main.moved` (warning) | `main`'s latest stamp is later than `branched_from` |
| `waypoint.twin.moved` | `stage.twin.moved` (warning) | the record's stage no longer resolves to the record's reference, or is gone |
| `waypoint.time.reversed` | dropped | marks are ordered by `at`, so no later one can be earlier |
| `step.sequence.skipped` | `step.stage.skipped` | the noun was the waypoint's; the warning is M11's |
| `step.target.foreign`, `step.target.unknown`, `step.target.current` | unchanged | reworded for stages |

**Rationale**: Constitution X and FR-014. The rename of `step.sequence.skipped` is the one
identifier outside the waypoint rules that moves; a stable identifier whose words name a
thing that no longer exists would mislead.

<a id="r-09"></a>
### R-09 The findings contract moves non-additively at version 1; the frozen copies

**Decision**: `contracts/findings.schema.json` loses the `waypoint` blocks and operations
and gains the `stage` ones, `waypoints.schema.json` is deleted and `stages.schema.json`
added under `https://github.com/happypathnetworking/fylgja/schemas/stages.schema.json`; `findings_version` stays `1`
(FR-022). The frozen `008-waypoints` copies under `internal/findings/testdata/contracts/`
go with their readers (`waypoint_test.go` and the M10 cases of `step_test.go`), since no
test holds a waypoint document any more. `twin.schema.json` `5` is frozen under
`internal/lab/testdata/contracts/010-verify/` for the records M12 wrote, beside `009-stepping`'s
`4`. `frozenContractCopies` becomes 29 (31 − 3 + 1). **Rationale**: a 0.x contract, and
the spec's decision; a frozen copy exists for a test, and a copy no test reads is dead.
**Alternative**: `findings_version` `2` (rejected by FR-022; the document's shape for every
other operation is unchanged).

<a id="r-10"></a>
### R-10 The recorded step histories' payloads are rewritten to the record's stage block

**Decision**: `step-cancelled`, `step-diverged` and `step-wait-cancelled` carry the
record's waypoint block inside their payloads, five lines each (§6.7): `InspectTwin`'s
result (the record the step read) and `RecordStep`'s input. With `TwinRecord.Waypoint`
gone, the replayed `InspectTwin` result would decode with no stage, the workflow would
refuse the twin as unsteppable, and the replay would issue different commands than the
history. So the payloads are decoded (base64 JSON), each `"waypoint": {series, sequence,
description, at_source}` rewritten as `"stage": {proposed_change: {id, branch}, label,
description, at_source}` with a label made from the series and sequence, and re-encoded,
once, by a script kept beside them; the replay tests' comment says so, as it says the
host's name and the diff were replaced. **Rationale**: the histories are already scrubbed
fixtures, not pristine recordings; the workflow's decisions depend on the block's
presence, never its content; re-recording a diverged step needs a fault on a live twin.
**Alternative**: a JSON key kept as `waypoint` for compatibility (rejected: the record's
shape is the contract's).

<a id="r-11"></a>
### R-11 `twin.json` `6`, and how older records read

**Decision**: `twin_version` `6`; `waypoint` becomes `stage`, an object or `null`:
`proposed_change {id, branch}`, `label`, `description`, `at_source` (`given`, `written`,
`branch_point`, `head`); the step block's sides carry `stage` where they carried `waypoint`.
A record of `5` or earlier reads as before, its waypoint block ignored: the twin shows as
pinned with no stage, and `twin step` refuses it as unsteppable ("created from a waypoint
of a version this build no longer reads; only a twin built from a stage steps"). `twin
show`, `twin verify`, `stage list` and the dry runs name the stage where they named the
waypoint, in the same places (FR-019). **Rationale**: FR-021; a waypoint twin's series is
gone with the kind, so it has nothing to step along.

<a id="r-12"></a>
### R-12 The fixture tool and test support

**Decision**: test support gains `TestBranchPrefix = "fylgja-test-"` and refuses any other
branch before a request, as it refused a series: `OpenProposedChange(branch, draft)`
returns the id and waits until every validator of the new proposed change is `completed`
(bounded, 180 s; about 17 s on a bare branch and 41 s on a seeded one, §6.4–§6.5), so an
intent change that follows is never re-rendered under a mark by the creation's pipeline;
`MarkStage(id, label, at, description)`, `StagesOf(id)`, `DeleteStagesOf(id)`,
`CloseProposedChange(id)`, `DeleteProposedChange(id)`, `ProposedChangesOf(branch)` (every
state), `RunCheck(id)` (asks `ARTIFACT` and waits for the validator's `completed_at` to
move, bounded 120 s), `Rebase(branch)` (`BranchRebase`, `wait_until_completion`, bounded
180 s), and `DeleteTestBranch(branch)`: the stages of each of its proposed changes, then
the proposed changes, then the branch. The fixture tool gains `-propose` (a draft on
`-branch`, printing the id), `-stage <label>` with `-at` and `-description`, `-run-check`
and `-close`; `-delete` deletes in order; `-waypoint` and `-delete-series` go. Every flag of
the group refuses `fylgja-fixture` and a `-branch` outside the prefix. The seed stays one
call, and the proposed change is opened after it (the wait makes the order safe), so tier
3 and the README add one command where they wrote a waypoint. `ArtifactsReadyAt` reads the
checksum's stamp, not the status's (§2.5). **Alternative**: opening the draft on a bare
branch before the seed, which the operator's own flow resembles (works too, and the
contract says so; the seed-then-propose order keeps the fixture tool's one-call seed).

<a id="r-13"></a>
### R-13 Tier 3's cases 7 and 8

**Decision**: case 7 seeds `fylgja-test-e2e-st-<pid>-<n>`, proposes, marks `seeded`, adds
the link, waits for the checksums, marks `third-link`; `stage plan --branch` lists four
stages (`branch-point` refused `contract.node.missing`, R-04; `seeded` and `third-link`
compiled to two ids; `head` compiled, to a third id, since its `at` differs) and three
steps (not computed; the link added with `n1` and `n3` changed; `unchanged`); `stage list`
lists them with no record; the twin from `seeded` carries the plan's id and a `6` record
naming the stage and the proposed change; `twin show` and `stage list` mark it; a step with
no target goes to `third-link`; a second step with no target goes to `head`, `unchanged`,
and the record moves (US2 scenario 2); destroy; `-delete` removes stages, proposed change
and branch, and `stage list --branch` after it is refused `stage.unknown`. (As T044 built
it and tier 3 asserts it, `stage list --branch` after `-delete` lists no row, exit 0, as a
listing refuses nothing but the kind's absence and a reserved label, and `stage plan
--branch` is refused `stage.unknown`, exit 1.) Case 8 does the
same on the mixed fixture with `seeded` and `mixed-link`, the step forward with
`--allow-restart` and back with `--stage <branch>/seeded`, as today. The trap's `-delete`
covers both. **Rationale**: FR-029 and the spec's independent tests, at the cost of about
90 s (two proposed-change waits) and one unchanged step.

<a id="r-14"></a>
### R-14 The API stays version `1`; the contracts say what moved

**Decision**: `stage.list` and `stage.plan` replace `waypoint.list` and `waypoint.plan` at
`/v1/stage/list` and `/v1/stage/plan`, `twin.create`, `twin.step` and `intent.read` take
`stage` where they took `waypoint`, and `api.Version` stays `"1"`; `api.md`'s operations
table and `api.schema.json` move, and `api.md` and `cli.md` each gain a section "014: the
stage surface" saying what moved and what each command needs, as they do for M10–M13.
**Rationale**: FR-023 and SC-008 move the surface and no version; the API is pre-1.0.

<a id="r-15"></a>
### R-15 The reference, the reserved labels and the derived stages' names

**Decision**: `<branch>/<label>`, split at the first `/`; the branch `^[^/\s]+$` as before,
the label `^[^/\s]+$` (R-01); `branch-point` and `head` name the derived stages; a mark
carrying either is `stage.label.reserved` wherever stages are listed or resolved, and the
derived stage of that name stays the derived one. In every block and record the derived
stages carry `label` `branch-point` or `head` and `at_source` `branch_point` or `head`, an
empty description, and the branch point's `branch` is `main`, the branch its read is on,
with the proposed change's source branch beside it. **Rationale**: the clarifications and
FR-008; the branch point is read on `main` (§1 R-03) and the record's `provenance.branch`
says so.

<a id="r-16"></a>
### R-16 `twin step`'s current stage is a position by label; "current" is the resolved reference

**Decision**: with no target, the next stage after the record's in the proposed change's
order, the record's position found by its label (`branch-point`, a mark's label, `head`);
nothing after it, or its label gone, is `step.target.unknown`, saying so and, when the head
has moved since the record, that `--stage <branch>/head` steps to it. A given target that
resolves to the record's own `(branch, at)` is `step.target.current`; one of another
proposed change (by id) or another branch is `step.target.foreign`; the marks strictly
between the two positions are `step.stage.skipped`. A head that has moved is a valid target
(FR-018; US2 scenario 6). **Rationale**: a reference names a position in the story and a
pinned instant; the two differ only when the story has moved under the twin.

---

<a id="6-verified-at-plan"></a>
## 6. Verified at plan (2026-10-16, development host, Infrahub 1.11.2)

Read-only unless said; every write was on a throwaway `fylgja-test-plan-*` branch, deleted
after, and the install ended as it began: branches `main` and `fylgja-fixture`,
`CoreProposedChange 0`, `FylgjaStage 0`, `FylgjaWaypoint 0`, `main`'s hash `e7386419…`.

### 6.1 An empty branch point reads `contract.node.missing`

`fylgja intent read --branch main` through the running server: `rejected`,
`contract.node.missing` on `main`, "branch defines FylgjaContract but holds no instance
of it", before any device is counted. The same for `--branch fylgja-fixture --at
2026-10-08T05:47:52.538186Z`, the fixture's own `branched_from`. GraphQL pinned there on
the fixture branch: `FylgjaDevice 0, FylgjaLink 0, FylgjaContract 0`. So on this install
every branch point is refused at conformance (R-04).

### 6.2 The migration's diffs

`infrahubctl schema check --branch main` (read-only) of the final kind: `changed:
FylgjaStage: attributes: added: description; changed: label: description, parameters.regex`.
Of a document holding `name: Waypoint, namespace: Fylgja, state: absent` alone: `removed:
FylgjaWaypoint`. Of a directory holding the generics, the reference schema, the final kind
and the absent document together: both diffs, plus the four `display_labels` deprecation
warnings the shipped files already carry. Exit 0 each.

### 6.3 `state: absent` removes the kind and is a no-op after

On `fylgja-test-plan-absent`, created with `BranchCreate`: `schema load` of the absent
document returned after 38 s and `GET /api/schema?branch=` no longer listed
`FylgjaWaypoint` (the branch's hash moved to `96c625ec…`; `main`'s did not). `schema
check` of the same document on that branch then printed `No diff`, `schema load` printed
"already up to date" in 1.8 s, and the whole directory with the document checked `No
diff`. So the removal document is idempotent and could ship; it does not, because the tree
holds no waypoint file by the spec (R-01).

### 6.4 A draft proposed change on a bare branch

On `fylgja-test-plan-pc`, created with the schema alone (22 s): `Branch(name:)` returned
`branched_from 2026-10-16T19:22:50.878965Z`, `created_at …50.878867Z` (98 µs earlier),
`origin_branch main`, `status OPEN`; `Branch(name:)` of a name that does not exist returned
`[]`. `CoreProposedChangeCreate` with `is_draft: true`: `Data Integrity` queued at 12 s and
`completed`/`success` at 17 s, and no other validator ran, so a bare branch's creation
pipeline is one validator in about 17 s. `FylgjaStageCreate` with `label: head` was
accepted (`display_label head`): Infrahub does not know the label is reserved (R-15). The
stage's `label.updated_at`, `as_of.updated_at` and `proposed_change.properties.updated_at`
read one stamp, `19:26:07.357145`. `FylgjaStage(proposed_change__source_branch__value:)`
listed it with its proposed change's `state` and `is_draft`. `_updated_at` is not a field
of `CoreProposedChange`.

### 6.5 The identical-bytes run-check re-runs the artifact validator

On `fylgja-test-plan-stale2`, seeded (17 s; checksums stamped `19:35:10`): a draft proposed
change's three validators concluded after 41 s (`Data Integrity`, `Schema Integrity`,
`Artifact Validator: srlinux_device_config`, `completed_at 19:35:52.068456`), the
checksums unmoved (identical bytes). `-set-site` moved every device's `site.updated_at`
(`19:35:50`). A hand `-generate` moved no checksum. `CoreProposedChangeRunCheck(check_type:
ARTIFACT)` at `19:35:54`: the **same** `CoreArtifactValidator` node (`…86a24e`) read
`in_progress` at 16 s with `started_at 19:36:05`, and `completed`/`success` at 21 s with
`completed_at 19:36:12.298111`; the checksums stayed `19:35:10`. Pinned at the run-check's
moment, the validator read `completed_at.value 19:35:52` (the value in force) but
`updated_at 19:36:12` (the current metadata), so the staleness rule compares
`completed_at`'s **value**, never its `updated_at` (R-05). `CoreArtifactValidator(proposed_change__ids:)`
answers pinned, with `definition { node { name } }` naming the definition.

### 6.6 The stamps through the generics

On `fylgja-fixture`, unpinned: `FylgjaDevice`'s attributes carry `updated_at`
(`name`, `role`, `site`: `05:47:58.232738`), its `platform` edge `properties.updated_at`
(the same), each interface's edge and attributes (`ethernet-1/1`: `05:48:00.978841`), the
interface's `link` edge (`05:48:03.562937`, the cabling), and an unset `parent`'s
`properties.updated_at` `null`; `FylgjaLink.endpoints.edges.properties.updated_at`
(`05:48:03.562937`); `FylgjaContract.version.updated_at`. `artifacts` must be spread `...
on CoreArtifactTarget`, as the read's fragment does: selected directly on `FylgjaDevice` it
is refused "Cannot query field 'artifacts' on type 'FylgjaDevice'". The fixture's
`checksum`, `status` and `storage_id` share the first generation's stamp
(`05:48:38.544482`).

### 6.7 The recorded histories carry the record's waypoint block

Decoding every payload of the nine histories under `internal/provision/testdata/`:
`step-cancelled`, `step-diverged` and `step-wait-cancelled` each carry five lines naming
`"waypoint": {"series": "fylgja-test-pause-30395", "sequence": N, "description": "…",
"at_source": "written"}`; the six provisioning histories carry none. The plain-text grep of
the tree does not see them (R-10).

### 6.8 The shell

`id -nG` names `docker` and `clab_admins`: `make diagrams` runs from a session's shell.

---

<a id="7-owed"></a>
## 7. Owed at implement

- **The migration on the development host's `main`**: `fylgja-fixture -prepare-main` with
  the new `schema/`, then `infrahubctl schema load migration/fylgja-waypoint-absent.yaml`
  (or `-prepare-main` extended to load it), both verified on `/api/schema`, then `make
  sdl` and `make generate`; the migration is the first task, since the generated client
  needs the SDL, and the removal comes after the waypoint code and its `Waypoints` query
  have left the tree, since genqlient validates every query against the SDL (tasks T003
  and T042; the SDL fetched again after the removal).
  `main`'s hash moves again; `fylgja-fixture` keeps `0aba31a5…` and `47b2c449…`.
- ~~**D-046** (R-05), the operator's~~ Done: accepted at `analyze`, 2026-10-16, and
  appended to `docs/decisions.md` as [D-046](../../docs/decisions.md#d-046); the
  validator's completion counts, and T015 builds the rule as the entry states it.
- **The README's three ways to write a stage**: a peer with no human-friendly id is
  referenced by `id` in an object file and in `infrahubctl object create --set`; verify each
  on a throwaway proposed change before the guide is committed (the objects skill's
  reference says "by `id` or HFID" and shows no example).
- **`stage.main.moved` exercised by a write on `main`** stays untried, as §4 left it; the
  mechanism is the head's.
- **A `display_label` through the proposed change** (`{{ proposed_change__source_branch__value }}/{{ label__value }}`)
  so the UI's breadcrumb reads as the reference does: unverified, deferred to a later pass.
- **The upstream request** for named points in time, once the pass works (§4).
- **Tier 3's wall time** with two proposed-change waits and the unchanged step, recorded
  in `docs/development.md` once measured.

---

<a id="8-verified-at-implement"></a>
## 8. Verified at implement

### 8.1 The shipped file checks as §6.2's (T002, 2026-10-16, read-only)

`schema/fylgja-stage.yaml`, copied from [contracts/stage-kind.md](contracts/stage-kind.md)
"The file" by extraction, not by hand. `infrahubctl schema check --branch main schema/`
against `main` (hash `e7386419…`, the candidate kind on it): each file `Valid`, the four
`display_labels` deprecation warnings, and one diff, `FylgjaStage: attributes: added:
description; changed: label: description, parameters.regex`; `FylgjaWaypoint` none.
Nothing was loaded: T003's step 1 holds before its load.

### 8.2 `infrahubctl schema format` does not keep the contract's key order (1.23.2)

The contract says the file's keys are in canonical order, "so a later `infrahubctl schema
format` moves nothing". The SDK's formatter disagrees: `schema format --check --diff
schema/fylgja-stage.yaml` exits 1 and would put `order_by` before `display_label`,
`generate_profile` and `branch` after `uniqueness_constraints`, and `label`'s `optional`
after its `parameters`; nothing else. Of the other shipped files, `fylgja-waypoint.yaml`
is canonical, and `fylgja-generics.yaml` and `reference.yaml` are not. No gate runs the
formatter, and T002 ships the contract's order; reordering is open, for the operator.

### 8.3 The final kind on `main`, a migration of the candidate (T003, 2026-10-16)

On the operator's word (the route's Run 2), from the repository root with `local/.env`
loaded, no twin, and before it `main` at `e7386419…` with `CoreProposedChange`,
`FylgjaStage` and `FylgjaWaypoint` each 0:

- `infrahubctl schema check --branch main schema/` (21:16:39Z, 10.6 s, exit 0): the four
  files `Valid`, the four `display_labels` deprecation warnings, and one diff,
  `FylgjaStage: attributes: added: description; changed: label: description,
  parameters.regex, regex`; `FylgjaWaypoint` none. The `regex` beside `parameters.regex`
  is Infrahub's mirror of it, not a second change: the waypoint's `series`, whose file sets
  `parameters.regex` alone, reads both equal on `main`, and after the load `label` does
  too. §6.2 and §8.1 name the same diff without the mirror.
- `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` (21:17:11Z, 37 s with the
  build, exit 0): `schema loaded on main`, `group fylgja-devices present`, `repository
  fylgja present (…, ref main)`, `import complete after 2s`. Its wait looks for
  `FylgjaContractCreate`, which `main` already had, so it does not wait for this
  migration's rebuild; the reads below came after it.
- `GET /api/schema?branch=main`: nodes `FylgjaContract`, `FylgjaWaypoint`, `FylgjaStage`
  and the four generics; `FylgjaStage` `branch: agnostic`, attributes `description`,
  `as_of`, `label` (Infrahub's order), `label` required with `regex` and
  `parameters.regex` both `^[^/\s]+$`, `proposed_change` and the uniqueness constraint as
  the candidate's; `CoreProposedChange.fylgja_stages`, peer `FylgjaStage`, identifier
  `proposed_change__fylgja_stages`, unchanged. GraphQL's `FylgjaStage` type has
  `description`.
- `GET /api/schema/summary`: `main` **`a8045729…`** (was `e7386419…`); `fylgja-fixture`
  `0aba31a5…`, unmoved.
- A second `schema check --branch main schema/`: `No diff`. After it: `Branch` `main` and
  `fylgja-fixture`; `CoreProposedChange 0`, `FylgjaStage 0`, `FylgjaWaypoint 0`.
- Through a server rebuilt from this tree, `intent read --branch fylgja-fixture` (schema
  `0aba31a5…`) then `twin compile` gave **`47b2c449…`**, as before (read-only; quickstart
  §1's tail, which T040 repeats).

`migration/fylgja-waypoint-absent.yaml` was not loaded: `FylgjaWaypoint` leaves at T042.
Tier 3 after it, on this tree's binary, with every seed loading `schema/` on a branch made
from the new `main`: `E2E-OK`, 17 m 51 s (21:26:44Z–21:44:35Z), the host clean after.

### 8.4 A dev server restarted after days down purges its expired runs first (Temporal CLI 1.9.1)

The dev server had been down three days, and before that a twin left following since
2026-10-08 (the README's walk-through, branch `fylgja-test-readme`, since deleted) had run
a check every 15 s. Restarted at 21:14Z, the server deleted the expired runs under the
namespace's 24 h retention at about nine a second (5,449 at 21:16Z, 7 at 21:26Z); until
it ended, a visibility list over many runs timed out (`temporal workflow list` without a
narrow query, `context deadline exceeded` or `RST_STREAM … CANCEL`), while `workflow
count` answered. So `twin show` and `twin verify` warned `show.service.unreachable`, and
tier 3's first run failed at case 1's verify, which requires no finding. After the purge
every list answered in 0.14 s and the rerun above passed. Before tier 3 on a restarted dev
server, wait for `temporal workflow count` to stop falling.

### 8.5 The SDL, the five queries and an unset filter (T004–T006, 2026-10-16, read-only)

- **The SDL.** `make sdl` from `main` (hash `a8045729…`) dropped the file's header, which
  was restored by hand as the `Makefile` says. Compared structurally with the committed one
  (each type's fields, arguments and interfaces, parsed, not as text): additions alone. The
  committed SDL predated even the candidate kind, so the diff adds `FylgjaStage` whole
  (with `description`), its edge, paginated and mutation types, `Query.FylgjaStage`,
  `CoreProposedChange.fylgja_stages` and its three input fields, and the `fylgja_stages__*`
  filters on `Query.CoreProposedChange`; `FylgjaWaypoint` is unchanged and nothing is
  removed. `completed_at` and `as_of` are `TextAttribute`s in GraphQL (a `String` value);
  `Branch(name:)` answers `[Branch!]!` with `branched_from` and `created_at` as strings.
- **An unset filter is no filter.** With `main` holding no proposed change, the question
  cannot be answered on `CoreProposedChange` read-only, so it was put to Infrahub's same
  attribute filter on two kinds that hold objects, `CoreAccountRole` (4) and
  `CoreAccountGroup` (2), by `name__value`: a variable sent as `null`, a variable omitted
  and a literal `null` each answered every object; `""` answered none; a name answered
  one. So `ProposedChanges` stays one query: its `$branch` is `omitempty`, so an empty
  branch is omitted rather than sent as `""`, and every open proposed change is listed.
  `CoreProposedChange(state__value: "open", source_branch__value:)` answered 0 with the
  variable null and omitted alike; tier 2 (T020) proves the listing on a real one.
- **Two names moved.** genqlient names each operation's function after the operation,
  so a query named `BranchInfo` or `Stamps` would collide with the reader's types
  `intent.BranchInfo` and `intent.Stamps`, which tasks T014 and T015 name. The queries are
  `BranchPoint` and `IntentStamps`; the contract's selections are unchanged, `IntentStamps`
  adding the platform's fields as tasks.md says.
- **Each operation as generated, live.** `ProposedChanges` (branch omitted, and
  `fylgja-fixture`) 0; `OrphanStages` 0; `BranchPoint` of `fylgja-fixture`
  `branched_from 2026-10-08T05:47:52.538186Z`, `created_at …52.538122Z` (`Z`, where the
  stamps read `+00:00`), of `main` `…05:43:47.307246Z`, of an absent name `[]`;
  `ArtifactValidations` of an unknown id, pinned, no edge; `IntentStamps` on
  `fylgja-fixture` unpinned and pinned, and on `main` (0 devices, 0 links).
- **The reader and the stamps, live** (a throwaway contract test, deleted after):
  `StageReader.Check` passes on `main`. `Stamps` on `fylgja-fixture`, unpinned and pinned at
  `…05:48:38.544483+00:00`: `Latest` `2026-10-08T05:48:38.544482+00:00` (n1's checksum,
  so the head's `at` is the one the contract's example gives); the three checksums are
  stamped `…38.543597`, `…38.544382` and `…38.544482`, each device's own (the artifacts'
  spread); intent `05:48:05.022364` (n1, n3) and `05:48:04.922669` (n2), each before its
  own checksum, so the fixture's head is fresh. Pinned at `…05:48:03.562938+00:00`, one
  microsecond after the cabling: no artifact yet, `Latest` the cabling's stamp. On `main`:
  `Latest ""`, no device.

### 8.6 The fixture tool's proposed changes, smoked (T008–T010, 2026-10-16)

From the repository root, Infrahub's address and token in the environment, no twin, on
`fylgja-test-tasks-1393696` (seeded, 16 s, the stage kind and its extension loaded on the
branch with `schema/` and accepted) and `fylgja-test-tasks-bare-1414083` (`-schema-only`),
with `main` holding `Branch` `main` and `fylgja-fixture`, `CoreProposedChange 0` and
`FylgjaStage 0` before and after:

- **The validators alone end the creation's wait too early.** On the seeded branch, the
  first `-propose` returned after 20 s with one validator, Data Integrity, completed
  (22:09:37); Schema Integrity appeared 20 s later and the artifact validator completed at
  22:10:20, 63 s after the create. Infrahub creates the validators one after another as
  the pipeline goes, so "every validator completed" holds in the gaps. **Nor do the
  pipeline's tasks end it**: `InfrahubTask(related_node__ids: [<id>])` lists about eight
  tasks naming the proposed change (generators, data and schema integrity, user tests,
  the artifacts' refresh, repository checks, then the artifacts' generation validation and
  the user checks), and a child task is listed only once it starts, about 2 s after its
  parent has ended: the second fixed attempt returned with 6 tasks, all ended, and 2
  validators, while the artifact validation's task appeared after. The first validator
  has no listed task at all. So `AwaitValidators` waits until there is a validator, every
  one is completed, and, when the branch's group `fylgja-devices` has members, a
  `CoreArtifactValidator` of the proposed change is among them: the creation renders inside
  that validator (§2.4), which is what the wait exists for, and it completed last in all
  three seeded runs. With that rule: **3 validators concluded in 38 s** on the seeded branch
  (§6.5 read 41 s), nothing after it in 20 s and no checksum moved (the seed's bytes);
  **1 validator in 9 s** on the bare branch (members 0), nothing more in 40 s (§6.4 read
  17 s).
- **Infrahub dropped one poll's connection** mid-pipeline (`Post …/graphql/main: EOF`, at
  22:12:33); the polls now read again until their deadline, as `WaitForArtifacts` does.
- `-stage seeded -description seeded`: written, `at` `label.updated_at`
  (`2026-10-16T22:16:31.827129+00:00`). `-run-check`: the artifact validator's
  `completed_at` moved to `2026-10-16T22:16:48.902133Z` **17 s** after the call (§2.4 read
  26 s, the contract about 21 s). `-stage head`: written, not refused (R-15). `-stage given
  -at <t>`: `given`, and Infrahub stored a nine-digit `as_of` verbatim (this host's `date`
  ignores `%6N`; Fylgja refuses it at resolution, `intent.at.precision`). A second
  `-stage seeded` is Infrahub's `Violates uniqueness constraint 'proposed_change-label'`
  and `-stage a/b` its `must conform with the regex`, each printed. `-close`: closed, the
  stages stay; `-stage` after it: `branch … has no open proposed change`.
- `-delete` on the seeded branch, which held four proposed changes (three closed while
  the wait was fixed, one closed by `-close`) and three stages: `deleted 3 stages, 4
  proposed changes, branch …` in 11 s; on the bare one `deleted 0 stages, 1 proposed
  change, branch …`. `main` read the same 20 s after (no proposed change canceled under a
  deleted branch).
- **Refused before any request** (neither variable set, so a request would have failed
  first on `INFRAHUB_ADDRESS`): `-propose -branch fylgja-fixture` and `-propose` alone ("the
  fixture has no proposed change"), `-stage x -branch other` and `-run-check -branch other`
  (the prefix), `-close -branch fylgja-fixture`, `-at` with neither `-stage` nor
  `-waypoint`, `-propose -close` (one at a time), and `-delete -branch other`. `-delete`
  keeps `fylgja-fixture`, which `make infrahub-clean` deletes and which holds no proposed
  change; any other branch outside the prefix is refused, as the contract's guard says.
- `Rebase` was not exercised here; T020's `TestStageRefusals` runs it.

### 8.7 The stages core against the real Infrahub (T020, 2026-10-16)

`internal/stages/stages_contract_test.go`, run twice from the repository root with
Infrahub's address and token in the environment and no twin: `go test -count=1 -tags
contract ./internal/stages/ -v`, first with `-run` naming the three tests (22:52Z, package
278 s) and then exactly as the task gives it (22:58Z, 262 s). Every test green both times:

| Test | First | Second |
|---|---|---|
| `TestStageKindLoads` | 22.8 s | 25.0 s |
| `TestStagesListAndPlan` | 104.1 s | 91.5 s |
| `TestStageRefusals` | 151.2 s | 144.8 s |

`main` read `Branch` `main` and `fylgja-fixture`, `CoreProposedChange 0`, `FylgjaStage 0`
before the first run and after each; every test's cleanup deleted its stages, then its
proposed change, then its branch.

- **The kind on `main`.** `GET /api/schema?branch=main`: `FylgjaStage` `agnostic`,
  uniqueness `[[proposed_change label__value]]`; `label` `Text`, required, `regex`
  `^[^/\s]+$` (`stages.LabelPattern`); `as_of` `DateTime` and `description` `Text`, both
  optional; `proposed_change` to `CoreProposedChange`, cardinality one, required; and
  `CoreProposedChange.fylgja_stages` to `FylgjaStage`, many. `StageReader.Check` passes.
  Loading `schema/` on a branch made from `main` left its hash `a8045729…`, `main`'s: an
  empty diff. The second `seeded` on one proposed change, written through the throwaway
  branch's GraphQL, was refused naming the uniqueness constraint, and `a/b` the regex.
- **The reader, live.** It read the open draft proposed change with its one stage (the
  label's stamp verbatim, no `as_of`), and with the branch filter empty it listed it among
  every open one: the unset filter §8.5 left for this test lists a real proposed change.
  `Branch` gave the harness's own `branched_from` and `created_at` strings, and nothing for
  an absent name. After `DeleteStagesOf`, no stage and no orphan.
- **The list and the plan.** Two marks with no `as_of`, `seeded` and `third-link` (after
  `SeedThirdLink` and n1's and n3's checksums awaited): four rows, `branch-point` on `main`
  at `branched_from`, each mark at its own `label.updated_at` verbatim (`written`), and the
  head one microsecond after the latest checksum stamp the harness read
  (`ArtifactsReadyAt`), with no finding. The plan: `branch-point` refused
  `contract.node.missing` (R-04) and its step not computed; `seeded`, `third-link` and
  `head` compiled to three ids (`a04ba782…`, `d83e49a0…`, `8f67f497…` the first time);
  the second step `+n1:e1-3 — n3:e1-3`, n1 and n3 changed for bootstrap and mapping, their
  artifacts moved; the third `unchanged; the ids differ by provenance alone`. SC-002:
  `seeded`'s filed CTM equals `stage.Read` of the branch at its `at` but for
  `observed_at`, and compiles to the plan's id.
- **The refusals, on one proposed change.** A role written on n1, n2 and n3 with no
  generate, then a mark: `stage.artifact.stale` on exactly n1, n2, n3, each naming both
  remedies; after `-generate` moved all three checksums, a fresh mark resolved. The site
  (rendered nowhere): a mark stale on all three; a generate moved no checksum and the next
  mark was still stale; `RunCheck`'s artifact validator completed 24 s and 23 s after the
  call, the checksums still unmoved, and the mark after it resolved, the product's
  `Validations` pinned at its `at` returning the harness's `completed_at` verbatim (D-046's
  hole closed live). The plan of the seven stages: the branch point refused
  `contract.node.missing`, the three stale marks `stage.artifact.stale`, the other two
  marks and the head compiled, and a step computed only between two compiled stages.
- **A rebase with nothing on `main` to take still moves the branch point.**
  `BranchRebase(wait_until_completion: true)` returned after **20 s and 17 s** on a seeded
  branch with an open draft proposed change and five marks (§2.7 read 67 s), with `main`
  unwritten since the branch was made: `branched_from` moved to the rebase's moment
  (`22:56:54.365315Z`, the branch created `22:55:02.356200Z`), `created_at` did not. The
  plan after it: all five marks `stage.at.before_branch_point`, each message naming `a
  rebase at <branched_from>` and the creation; the branch point still refused
  `contract.node.missing`; the head compiled, fresh, since the rebase stamps the intent
  and the checksums alike (§2.7).
- **The rest.** A mark labelled `head`, accepted by Infrahub, refused
  `stage.label.reserved` on `<branch>/head`; a mark with `as_of` one hour ahead refused
  `stage.at.unresolved`, "later than the current time"; after `CloseProposedChange`, a
  mark of the branch and the plan refused whole `stage.unknown` on the branch ("no open
  proposed change has source branch …"); a branch that does not exist `stage.unknown`.
- **The creation's pipeline** concluded 36–50 s after the create on a seeded branch (§8.6
  read 38 s) and 7 s on a bare one.

### 8.8 The hand scenarios before the removal (T040, 2026-10-17)

From the repository root with `local/.env` loaded and no twin, after `make build` and the
worker and the API's server restarted from this tree and verified as `CLAUDE.md` says
(02:49Z; their binary had read `(deleted)`). Before and after: `main` `a8045729…`, `Branch`
`main` and `fylgja-fixture`, `CoreProposedChange 0`, `FylgjaStage 0`, `FylgjaWaypoint 0`.
The fixture tool ran as a binary built from this tree, which is `go run`'s, but for the
rewritten §4, run from the quickstart verbatim.

- **§1's tail.** `intent read --branch fylgja-fixture` (schema `0aba31a5…`, 8.6 s) then
  `twin compile`: **`47b2c449…`**.
- **§3, on `fylgja-test-qs-2027373`** (02:54:48Z–02:57:51Z; seed 17 s, `-propose` 37 s,
  three validators), every output as the quickstart expects. The first plan: the branch
  point refused `contract.node.missing`, the head compiled, the step not computed,
  `rejected`, exit 1. After `seeded`, `-set-role stale-probe` and `stale`: `seeded`
  compiled; `stale` and the head refused `stage.artifact.stale` naming n1, n2 and n3, each
  message with both remedies. The three checksums moved 7 s after `-generate` returned, and
  `fresh`, marked after them, compiled with the head; `stale` was still refused, and the
  step `fresh → head` read `unchanged; the ids differ by provenance alone`. The head's `at`
  (n1's checksum stamp plus one microsecond, `02:56:06.117987`) is earlier than `fresh`'s
  written `02:56:07.077340`, and the head still sorts last, which is `TestOrderEndsFixed`
  seen live. The list: five rows, no twin marked, the branch point's `at` in Infrahub's
  `Z` layout (`branched_from` verbatim, as the reference contract says) and the rest
  `+00:00`. `intent read --stage <b>/fresh` and `--branch <b> --at <its at>`: `same`
  but for `observed_at`, and neither CTM holds the label or the word `stage`. `twin create
  --stage <b>/fresh --branch <b> --dry-run`: `stage.flags.conflict` naming `--branch`,
  exit 2, the server logging the request in 0 s. `stage plan --branch no-such-branch`:
  `stage.unknown`, `… the branches with one are: <b>`, exit 1. After a mark labelled
  `head`: `rejected` with `stage.label.reserved` on the mark, the derived head listed
  after it, exit 1. After `-close`: the list `branch <b>: no open proposed change`, exit 0;
  the plan `stage.unknown`, exit 1. `-delete`: `deleted 4 stages, 1 proposed change,
  branch <b>`; the list `no open proposed change`.
- **The first attempt's `fresh` was stale, and rightly** (`fylgja-test-qs-2016604`, deleted
  after it). The quickstart marked `fresh` straight after `-generate`, which returned in
  0.44 s: its wait is for the count and Ready, which a rewrite never leaves
  (`GenerateArtifacts`' comment). `fresh` was stamped 02:52:26.15 and the checksums
  landed at 02:52:30.7 (n2), 32.8 (n1) and 33.6 (n3); the plan refused `fresh` stale naming
  all three, and a plan after them compiled the head and still refused `fresh`, pinned
  before them. The quickstart now waits for the three checksums to move before the mark,
  as `scripts/e2e.sh`'s `await_checksums_moved` does. Its CTM comparison read `.at` and
  `.observed_at`, which the CTM keeps under `.envelope`: `--at null` went to Infrahub
  verbatim and was refused (`HTTP 400: Invalid time format for null`, `operation.failed`,
  exit 2). Both are corrected in the quickstart. Neither is a defect in Fylgja.
- **§4's rebase** (`fylgja-test-qs-rb-2034723`, then on `-2048414` as rewritten):
  `BranchRebase(wait_until_completion: true)` returned in 19 s, `branched_from` moved to the
  rebase and `created_at` did not; both marks refused `stage.at.before_branch_point`, each
  naming the rebase and the creation; the branch point `contract.node.missing`, the head
  compiled, exit 1.
- **Infrahub refuses a proposed change's delete while a stage names it.**
  `CoreProposedChangeDelete` answered `Cannot delete CoreProposedChange '<id>'. It is
  linked to mandatory relationship proposed_change on node FylgjaStage '<id>' at
  FylgjaStage.proposed_change` (`ATTRIBUTE_CONSTRAINT_VIOLATION`, `http_status` 422), and
  the proposed change and its stages were unchanged. The same answer came on both
  branches. This supersedes §2.3's "`CoreProposedChangeDelete` succeeds under a stage", which was
  verified while the kind was loaded on the throwaway branch alone (§2's setup, before §2.9
  loaded it on `main`), so `main`'s delete had no `FylgjaStage` in its schema to find. With
  the kind on `main`, as it ships, a proposed change is never deleted under its stages.
- **An orphan is made by removing the edge.** `RelationshipRemove(data: {id: <proposed
  change>, name: "fylgja_stages", nodes: [{id: …}, {id: …}]})` answered `ok: true`, and
  each stage then read `proposed_change { node: null }` despite `optional: false`. `stage
  list`: the proposed change with its two derived stages, then `orphaned: stage "one" (…)
  names no proposed change` and the same for `two`, two `stage.orphaned` warnings, status
  `ok`, exit 0; `stage plan` planned neither. The proposed change's delete then succeeded.
  `-delete` printed `deleted 0 stages, 0 proposed changes, branch <b>`. Nothing ties an
  orphan to its branch, so the orphans outlived the branch until `FylgjaStageDelete` by id.
  The quickstart's old expectation, that `-delete` removes them, could not have held under
  §2.3 either: with the proposed change gone, `-delete` finds none. §4 is rewritten to these
  steps and ran from the quickstart verbatim (03:04:15Z–03:05:42Z).
- **Corrected here**: `docs/verified-facts.md`'s fact; [contracts/stage-kind.md](contracts/stage-kind.md)'s
  guidance, which T046 carries into `schema/README.md`; and the comments in
  `internal/testsupport/proposed.go`, `cmd/fylgja-fixture/main.go` and
  `internal/stages/stages_contract_test.go` that gave §2.3's premise as the reason for the
  deletion order. The order stands: deleting the proposed change first is refused rather
  than leaving orphans.
- **Left for the operator.** These records still rest on §2.3's premise:
  - the `stage.orphaned` message, `… names no proposed change: its proposed change was
    deleted under it; delete the stage`, which the reference contract quotes and the
    tier-1 tests pin;
  - spec.md's edge case "A proposed change is deleted under its stages" and US3
    scenario 3's Given;
  - D-045's context ("Deleting a proposed change succeeds under its stages");
  - the glossary's "Orphaned stage";
  - the comments in `internal/intent` and `internal/stages` that name an orphan's cause.

  What they require holds for an orphan however it is made: a finding, never a crash, and
  nothing planned from it. Whether the wording names the edge's removal is a wording
  decision for the operator.
- **After**: `Branch` `main` and `fylgja-fixture`; `CoreProposedChange 0`, `FylgjaStage 0`,
  `FylgjaWaypoint 0`; `clab inspect --all` `{}`; no `local/twin`; no Schedule.

### 8.9 The waypoint kind leaves `main` (T042, 2026-10-17)

On the operator's word (the route's Run 14, the attended loop), from the repository root
with Infrahub's address and token in the environment, no twin, and before it `main` at
`a8045729…` with `Branch` `main` and `fylgja-fixture`, `CoreProposedChange 0`,
`FylgjaStage 0` and `FylgjaWaypoint 0`. The waypoint code and its `Waypoints` query had
left the tree at T030, and the test tooling's at T041.

- `infrahubctl schema check --branch main
  specs/014-proposed-change-stages/migration/fylgja-waypoint-absent.yaml` (03:31:26Z,
  9.5 s, exit 0): `Valid`, and the diff `removed: FylgjaWaypoint: null` alone.
- `schema load` of the same document (03:31:43Z): `loaded successfully`, `1 schema
  processed in 40.799 seconds` (42.8 s wall), as §6.3 read.
- `GET /api/schema?branch=main`: nodes `FylgjaContract` and `FylgjaStage`, generics
  `FylgjaDevice`, `FylgjaInterface`, `FylgjaLink` and `FylgjaPlatform`, no
  `FylgjaWaypoint`; `FylgjaStage`'s attributes `description`, `as_of`, `label` and its
  `proposed_change` (`CoreProposedChange`, one, required) unchanged, and
  `CoreProposedChange.fylgja_stages` (peer `FylgjaStage`, many, identifier
  `proposed_change__fylgja_stages`) unchanged. `{ FylgjaWaypoint { count } }` is now
  GraphQL's `Cannot query field 'FylgjaWaypoint' on type 'Query'`.
- `GET /api/schema/summary`: `main` **`e43a1cde…`** (was `a8045729…`), for T053;
  `fylgja-fixture` `0aba31a5…`, unmoved (a branch keeps the schema of its creation, so the
  fixture branch still carries the waypoint kind, which nothing reads).
- A second check of the absent document (03:32:32Z, 16.4 s): `No diff`. `schema check
  --branch main schema/` (03:33:43Z, 8.9 s): the three files `Valid`, the four
  `display_labels` deprecation warnings, `No diff`, so a seed's load of `schema/` on a
  branch made from the new `main` writes nothing.
- `make sdl` (2.0 s) dropped the header, restored by hand. Compared structurally with the
  SDL before it (graphql-core 3.2.13 from the venv: each type's kind, fields with their
  types and arguments, interfaces, enum values and union members): removed the types
  `FylgjaWaypoint`, `EdgedFylgjaWaypoint`, `NestedEdgedFylgjaWaypoint`,
  `PaginatedFylgjaWaypoint`, `NestedPaginatedFylgjaWaypoint`, the `Create`, `Update`,
  `Upsert` and `Delete` payloads with their three inputs, and the fields
  `Query.FylgjaWaypoint` and `Mutation.FylgjaWaypoint{Create,Update,Upsert,Delete}`;
  nothing added or changed. The SDL names no waypoint. `make generate` left
  `internal/intent/generated.go` unchanged; `go build ./...` passed.
- The `Makefile`'s `sdl` comment now says the stage kind and its extension live on the
  default branch.
- After it: `Branch` `main` and `fylgja-fixture`; `CoreProposedChange 0`, `FylgjaStage 0`.

### 8.10 Tier 2 whole, with no waypoint on `main` (T043, 2026-10-17)

`TestStageKindLoads` now also fails if `main`'s schema lists `FylgjaWaypoint`. `make
test-contract` from the repository root, Infrahub's address and token in the environment,
no twin, `main` at `e43a1cde…`:

- **The first run failed at go test's default timeout** (03:34:20Z, 604.8 s wall, exit 2).
  Every package passed but `internal/stages`, whose binary hit `panic: test timed out
  after 10m0s` with `TestStageRefusals` 3 m 52 s in, waiting on its `BranchRebase`. The
  rebase was not stuck: Infrahub's task `Rebase branch fylgja-test-st-…` ran 03:44:05Z to
  03:44:27Z, 22 s (§8.7 read 17–20 s). The package's three tests take 262–278 s alone
  (§8.7); beside `internal/stage` (503.0 s this run, 426.8 s in 013's last) and
  `internal/intent` (254.0 s), one Infrahub works every package's branches, proposed
  changes and rebases in turn, so `TestStageKindLoads` and `TestStagesListAndPlan` took
  about 6 m 8 s together where they took 2 m alone. The test's cleanup never ran under the
  panic: its branch, open proposed change and five stages were left, and `fylgja-fixture
  -delete -branch fylgja-test-st-1792208433-9527` printed `deleted 5 stages, 1 proposed
  change, branch …` (8.5 s), after which `main` read as before.
- **So `make test-contract` sets `-timeout 30m`**, its comment saying why. 10 minutes is
  go test's default, which no tier set before because no package came near it; 30 minutes
  leaves headroom and still ends a test that hangs.
- **The second run passed** (03:45:45Z–03:54:37Z): exit 0, **531.5 s** wall, every package
  `ok`, the longest `internal/stages` 527.2 s, then `internal/stage` 409.2 s,
  `internal/intent` 200.3 s, `internal/cli` 22.3 s. Against 013's last run on this host,
  431 s (`internal/stage` the longest then at 426.8 s), the tier is 100 s longer, less than
  the plan's "about three minutes", since both of `TestStageRefusals`' rebases took about
  20 s, not §2.7's 67 s. `internal/stages` is now the longest package and decides the
  tier's time. Its time across the two runs, over 600 s and then 527 s, shows the spread.
- After it: `{ Branch { name } CoreProposedChange { count } FylgjaStage { count } }` read
  `main` and `fylgja-fixture`, 0 and 0; `main` still `e43a1cde…`.

### 8.11 Tier 3 whole and narrowed, on stages (T045, 2026-10-17)

From the repository root with `local/.env` loaded, after `make build` and the worker and
the API's server restarted from this tree (03:58Z; both had read `(deleted)`) and verified
as `CLAUDE.md` says: each binary current, `INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT` and
`FYLGJA_API_TOKEN` in the environment, both reports naming both packages with their logins
set, the server `listening on 127.0.0.1:7650 (API version 1, build 0.1.0-dev)`. The dev
server was up. Before: no lab, no twin directory, no Schedule, `Branch` `main` and
`fylgja-fixture`, `CoreProposedChange 0`, `FylgjaStage 0`; `free -m` 19.3 GiB available,
Infrahub's eight containers at about 7.8 GiB, four minutes after T043's tier 2.

- **`make test-e2e`** (03:59:03Z–04:17:58Z): **`E2E-OK`**, exit 0, wall **1125.5 s**
  (18 m 46 s), against 013's 17–19 minutes, which made one twin more and opened no proposed
  change. Case 1 deployed `47b2c449…`. Case 7: seed 23.8 s, the draft proposed change and
  its three validators 46.0 s, n1's and n3's artifacts moved and Ready 7.6 s after the
  generate returned, the plan 5.7 s (exit 1, the branch point refused; one link added, n1
  and n3 changed; the head unchanged), the create from `seeded` 45.9 s deploying the id the
  plan printed for it, the step to `third-link` 15.6 s and the `unchanged` step to the head
  10.0 s (command wall), destroy 2.3 s. The head's `at` (`04:10:20.359571`) is earlier than
  `third-link`'s written `04:10:21.003498`, and the head still planned last. Case 8:
  proposed change 41.4 s, create 88.1 s, the step to `mixed-link` refused
  `step.restart.required` naming e1 (dry run and run), then taken with `--allow-restart` in
  72.3 s (e1 restarted in place, s1 and e2 untouched, the link seen from both ends 0.8 s and
  0.5 s after), the step back with `--stage <b>/seeded` 69.7 s, the waits settled after
  4.586 s and 3.356 s. Creates 43.7–90.6 s; verify 4.9 s, 3.9 s and 3.0 s.
- **`PLATFORMS=nokia_srlinux make test-e2e`** (04:21:45Z–04:32:55Z, after T046's Infrahub
  writes and about four minutes' rest from twins): **`E2E-PARTIAL: platforms nokia_srlinux;
  ran 1 2 3 4 5 7; skipped 6 (needs arista_eos: not in PLATFORMS) 8 (needs arista_eos: not
  in PLATFORMS)`**, exit 0, wall **665.7 s** (11 m 6 s), against the README's "about 12
  minutes". Case 7 as in the whole run: proposed change 42.7 s, plan 5.0 s, create 41.8 s,
  steps 14.2 s and 9.9 s. The skip reasons name the list alone, since the cEOS image is
  present on this host.
- After each: `clab inspect --all` `{}`, no `local/twin`, no Schedule, `Branch` `main` and
  `fylgja-fixture`, `CoreProposedChange 0`, `FylgjaStage 0`. No case failed, so nothing was
  fixed. Both wall times are for T051.

### 8.12 The three ways to write a stage (T046, 2026-10-17)

On a throwaway proposed change, between T045's two runs, no twin: `fylgja-fixture -branch
fylgja-test-schema-readme-2389915` (19.0 s), then `-propose` (40.6 s; proposed change
`18df3629…`, draft, three validators concluded), `infrahubctl` 1.23.2 from `.venv`
connecting as Admin, with no `--branch` (the default branch, which has the kind).

- **An object file**: `kind: Object`, `spec.kind: FylgjaStage`, two rows, `proposed_change`
  the proposed change's id as a bare string, one row with `as_of: "2026-10-17T04:19:35Z"`.
  `infrahubctl object validate` printed `Valid!` (exit 0) and `object load` `Created node:
  FylgjaStage : <id>` for each (exit 0, 2 s). The loader takes an id for a peer with no
  human-friendly id, which the objects skill's reference ("by `id` or HFID") showed no
  example of.
- **`infrahubctl object create FylgjaStage --set label=verified --set proposed_change=<id>
  --set description="checked by hand"`**: `Saved FylgjaStage (ID: <id>)`, exit 0.
- **`fylgja stage list --branch <b>`**: the proposed change with its id, `draft (5
  stages)`: the branch point, `cut-over` at `2026-10-17T04:19:35Z (given)` verbatim, then
  `cabled` and `verified` `(written)`, then the head; exit 0. The given row sorts by its
  `at`, before the two written later.
- **Deleting by id**: `infrahubctl object delete FylgjaStage <id> --yes` printed `Deleted
  FylgjaStage 'cut-over' (ID: <id>)`, and the list lost the row.
- **The UI's entry**: `GET /api/menu?branch=main` has no "Fylgja" group: `Stage` is an
  entry of its own in the object section (`/objects/FylgjaStage`), beside `Fylgja
  contract`, Device, Interface, Link and Platform. The contract's "Stage, under the Fylgja
  menu" is corrected in `schema/README.md` to what the menu holds; the form itself (the
  proposed change chosen from its list) is described as the contract gives it, untried
  headless.
- `fylgja schema check --branch <b>`: `stages: FylgjaStage present on the default branch,
  with its extension`, exit 0.
- `-delete` (7 s): `deleted 2 stages, 1 proposed change, branch <b>`. After:
  `Branch` `main` and `fylgja-fixture`, `CoreProposedChange 0`, `FylgjaStage 0`.
- `schema/README.md`'s "Waypoints: writing one" is replaced by "Stages: marking one" in the
  contract's order, with these commands and the file table's row for
  `fylgja-stage.yaml`.

### 8.13 The README's walk-through by hand (T048, 2026-10-17)

"A stepping twin" as T047 rewrote it, followed command by command on the development host
after T045's narrowed run, with the worker and the API's server of §8.11 (this tree's
build), every `fylgja` command through the server on `127.0.0.1:7650`, the fixture tool by
`go run` as the README gives it. 04:33:43Z–04:37:44Z.

- **`-delete`** first: exit 1, `deleting branch fylgja-test-readme: graphql: Branch:
  fylgja-test-readme not found`, since this run began at the stepping section; a reader who
  followed "A walking twin, start to finish" has the branch, which the section's opening
  sentence says. Left as the README gives it.
- **Seed** 19.9 s; **`-propose`** 36.8 s (`18df36fe…`, draft, three validators in 36 s);
  **`-stage seeded`** marked at `04:34:59.424352+00:00 (written)`; **`-add-link`** returned
  and n1's and n3's checksums moved **7.6 s** after it (T047's run read 10 s), n2's not;
  **`-stage third-link`** marked after them, at `04:35:09.759424+00:00`.
- **`stage plan`**: the README's lines exactly but for the ids and stamps: the branch point
  refused `contract.node.missing`, `seeded` `b63404c3…`, the step adding the link and
  changing n1 and n3, `third-link` `d05dc990…`, the step to the head `unchanged`, the head
  `6ecc489c…` at `04:35:08.687492` (n1's checksum stamp plus one microsecond, before
  `third-link`'s written at, still last); exit 1.
- **`twin create --stage fylgja-test-readme/seeded`**: deploy 43.2 s, the three nodes ready
  in 0.1–0.4 s, `twin ready: bundle_id b63404c3…`, `pinned at … not following`; 50.4 s
  wall, exit 0.
- **`twin step --dry-run`**: the README's lines but one: `memory: sum 6144 MiB; host budget
  22873 MiB`, where the README said `host budget unset`. `scripts/bring-up.sh` writes
  `FYLGJA_HOST_MEMORY_MB` into `local/.env` (MemTotal less 8 GiB), so a host the script set
  up prints its budget. Nothing follows `verdict: clear`; the README's `…` after it was
  removed. Exit 0.
- **`twin step`**: `stepped to stage fylgja-test-readme/third-link (bundle d05dc990…) in
  4.5s: reconcile 0.8s; push n1 2.5s, n3 2.6s; settled after 6.1s`, 14.0 s wall, exit 0.
  The three containers kept the create's start time (`04:35:31.44Z`), so none restarted,
  and n2 was neither reconciled nor pushed. Nothing follows the `stepped` line; the README's
  trailing `…` was removed.
- **`twin verify`**: 19 assertions over 3 nodes, the third link held from both ends, `held:
  3 host names, 8 ports, 8 link ends, 3 record claims`, exit 0. **`stage list`**: four rows,
  `← twin` beside `third-link`, exit 0.
- **`twin step --stage fylgja-test-readme/seeded`**: `links: -n1:e1-3 — n3:e1-3`, `in 4.8s:
  reconcile 0.6s; push n1 2.8s, n3 2.8s; settled after 4.9s`, 14.1 s wall, exit 0, no
  restart.
- **`twin destroy`** (3 containers, the twin directory removed), then **`-delete`**:
  `deleted 2 stages, 1 proposed change, branch fylgja-test-readme`. After: `clab inspect
  --all` `{}`, no `local/twin`, no Schedule, `Branch` `main` and `fylgja-fixture`,
  `CoreProposedChange 0`, `FylgjaStage 0`.
- **The README corrected** to these outputs: the ids, stamps, run ids, timings and the
  verify's addresses (n2 and n3 swapped this time), the checksums' wait "8 to 10 seconds",
  the budget line, and the two trailing `…`. The walking-twin section's lines, which this
  run did not follow, are untouched.
- **Seen, not changed**: `stage list` pads the reference, the branch and the source but not
  the `at`, so the descriptions line up only when every `at` has one width. The branch
  point's comes back in Infrahub's `Z` layout (27 characters) and a mark's in `+00:00` (32),
  so its description sits five columns left of the others; a given `as_of` written short
  (§8.12's `2026-10-17T04:19:35Z`) sits further left. The commands contract asks only that
  "the ats line up", which holds; its example has every `at` in one layout, and
  `printList`'s comment in `internal/server/stages.go` says the descriptions line up too.
  Cosmetic, outside T048: left for the operator or a later pass.

### 8.14 Convergence pass 1 against the real Infrahub (T057, T058, 2026-10-17)

Tier 2's `internal/stages`, with no twin and no other tier running, Infrahub holding
`main` and `fylgja-fixture` alone before and after:

- **The package whole** passed in 322.7 s (325.9 s wall): `TestStageKindLoads` 40.0 s,
  `TestStagesListAndPlan` 116.3 s, `TestStageRefusals` 165.8 s. Each cleanup deleted its
  own: 0, 2 and 7 stages, one proposed change each, and its branch.
- **An unknown stage of an open proposed change** (T057): `<branch>/nosuch`, resolved after
  the rebase and the reserved and future marks, is one `stage.unknown` naming the stages
  in Fylgja's order, the mark labelled `head` not among them, since it shares the derived
  head's place.
- **Nothing left** (T058): after `DeleteTestBranchCounting`, `Branch(name:)` lists no
  branch, `CoreProposedChange(source_branch__value:)` lists nothing in any state, and
  `FylgjaStage(ids: [...])` on the default branch returns none of the stages collected
  before the deletion. Both reads see the branch and every stage before the deletion
  (`TestStagesListAndPlan` alone, 84.5 s: two stages before, none after), so the empty
  reads after it are the deletion's.
- **The gates after the pass**: `make build` static; `make test` passed, 35.2 s uncached
  under a load average of about 5 (`internal/cli` 25.1 s, against 24.1–24.8 s at T038),
  and 38.3 s on its first run of the pass; the pass's new and extended `internal/cli` cases
  take about 0.15 s of that. The 35 s budget sits inside the run-to-run spread, as T038's
  note found, and is still the operator's. `make lint` 0 issues; `go vet -tags
  contract,fixture,e2e ./...` clean; no golden moved; `fylgja --help` names no waypoint.

### 8.15 Editing a mark (T075, 2026-10-17)

`TestStagesListAndPlan` alone, with no twin booted and no other tier running, passed in
96.5 s (99.8 s wall). After its plan, on its own open proposed change, it edited its first
mark, `seeded`, written with no `as_of` and so at its label's stamp
`2026-10-17T07:11:33.236706+00:00`, three times through `FylgjaStageUpdate` on the default
branch (`testsupport.UpdateStage`), finding the proposed change again after each:

- **A `description` edit alone** left `label.updated_at` at `…07:11:33.236706+00:00`: the
  mark read its new description at the same `at`, `written`, and `stages.Moved` against a
  record view of its first resolution filed nothing. The 09-28 reading of M10's kind, that
  a description edit leaves another attribute's stamp where it was, holds for the stage
  kind.
- **A relabel** to `relabelled` moved `label.updated_at` to the relabel's write,
  `…07:11:57.578379+00:00`, 24 s later: the new reference is at that stamp, `written`; the
  old `<branch>/seeded` resolves to one `stage.unknown`; and `Moved` files one
  `stage.twin.moved` warning saying `<branch>/seeded no longer exists`. A mark with no
  `as_of` names the moment of its last relabel, not of its first write.
- **An `as_of`** of the first `at`, `2026-10-17T07:11:33.236706+00:00`, gave the mark that
  `at` back verbatim, `given`, and left `label.updated_at` at the relabel's write.
- The cleanup deleted 2 stages, 1 proposed change and the branch; afterwards `Branch` lists
  `main` and `fylgja-fixture` alone, and `CoreProposedChange { count }` and `FylgjaStage {
  count }` read 0.

So `schema/README.md`'s "Editing a stage" and `contracts/stage-kind.md`'s bullet, which
said a `label` edit only renames the reference, now say that a relabelled mark with no
`as_of` names the moment of the relabel, and that writing its `at` as its `as_of` first
keeps its moment.

### 8.16 The platform's stamps (T076, 2026-10-17, read-only)

On `fylgja-fixture`, through the raw query and then through `(*intent.Client).Stamps` with
the regenerated `IntentStamps`, which selects the platform's `vendor`, `nos` and `version`
with their `updated_at` (fragment `PlatformStamps`), no twin booted:

- **Unpinned**, the fixture's one platform (all three devices name the same node) reads
  `vendor` `nokia`, `nos` `srlinux` and `version` `24.7`, each `updated_at`
  `2026-10-08T05:47:56.812998+00:00`, as is its unset `model`'s: the seed wrote the platform
  first, 1.4 s before n1's own stamps (`05:47:58.232738`).
- **Pinned at the head** (`2026-10-08T05:48:38.544483+00:00`), the same three stamps; pinned
  one microsecond after n1's stamp, one device and the same three; pinned at exactly n1's
  stamp, the node and no value, its platform edge and node `null`, as §2.6 found for any
  attribute.
- **Through the client**, unpinned and pinned at the head: `Latest`
  `2026-10-08T05:48:38.544482+00:00`, n1's and n3's intent `…05:48:05.022364`, n2's
  `…05:48:04.922669` (the cabling), each artifact's checksum as before, each platform
  `{nokia srlinux 24.7}`. The platform's stamps are older than every device's, so no
  device's intent, no `Latest`, no head and no fixture id moves.

Genqlient cannot merge two fragment spreads that select one field (`...PlatformFields
...PlatformStamps` generates `GetVendor`, `GetNos` and `GetVersion` twice and does not
compile), so `PlatformStamps` carries the values beside the stamps and the stamps read
projects the platform from it.

### 8.17 A link deleted as the branch's latest write (T077, 2026-10-17)

A throwaway contract test in `internal/stages`, deleted after: its own `fylgja-test-st-*`
branch, the schema loaded and `SeedThreeNode`, a draft proposed change whose validators
it awaited (`propose`), a mark `seeded` with no `as_of`; then the seeded link
n1:ethernet-1/1 — n2:ethernet-1/1 deleted by `NetworkLinkDelete(data: {id})` on the branch,
the kind's delete as the seed writes it (`NetworkLinkCreate`); no twin booted, no other
tier running. It ran three times; the figures are the third's (`fylgja-test-st-1792245248-1945`,
98.4 s), and the first two agree in every reading. Each cleanup deleted 2 stages, 1
proposed change and the branch, and Infrahub held `main` and `fylgja-fixture` alone after,
no proposed change and no stage.

- **Before the delete**, `Stamps` unpinned: `Latest` `13:54:23.955205` (n1's checksum);
  n1's and n3's intent `13:54:16.873735` (the n3–n1 cabling), n2's `13:54:16.775152`; the
  deleted link's endpoint edges and both interfaces' `link` edges `13:54:16.636426`. The
  head `13:54:23.955206` reads 3 links, as the unpinned read does.
- **The delete** was sent at `13:55:08.922043` and returned at `13:55:09.034750`.
- **After it, before any generate**, `Stamps` unpinned reads exactly what it read before:
  `Latest`, each device's intent and each checksum unmoved, so the head is
  `13:54:23.955206` still. The link is gone, so no endpoint edge of it is read, and both
  interfaces' `link` edges read `properties.updated_at` `null` with `node` `null`, which the
  fold skips (§6.6); their own attributes keep their stamps (`13:54:15.523129`,
  `…15.960905`). **No stamp the `IntentStamps` query reads moves.**
- **The head reads the link; an unpinned read does not.** Pinned at the head, 3 links;
  unpinned, and pinned at the delete's return, 2. `Stamps` pinned at the return reads the
  same stamps as unpinned.
- **A mark after the removal is not refused.** `removed`, marked with no `as_of` at
  `13:55:10.328713`, resolves `written` with no finding: its pinned read holds 2 links,
  and its artifacts, which still render `description to n2 ethernet-1/1` on n1 and its
  counterpart on n2, are stamped after every intent stamp the rule reads. `stage plan`
  compiles `seeded` (3 links), `removed` (2) and the head (3): the step `seeded → removed`
  is `links: -n1:e1-1 — n2:e1-1` with `artifacts: unchanged`, and `removed → head` puts the
  link back, `links: +n1:e1-1 — n2:e1-1`. The branch point is refused
  `contract.node.missing`, as on this install it always is (R-04).
- **A generate covers it.** `GenerateArtifacts`, then n1's and n2's checksums moved
  (`13:55:29.597940`, `…29.590055`; n3's, whose rendering names no deleted link, stayed
  `13:54:23.543788`), so `Latest` and the head moved to `13:55:29.597941`, which reads 2
  links. The plan then compiles the head with 2 links, `removed → head` `links: unchanged`,
  `artifacts: n1 device-config f1f4ce3b… → 2c2143b5…; n2 device-config e6065da6… →
  9c1ea4bc…`; `removed` still resolves `written` with no finding, its artifacts at its `at`
  the pre-removal bytes.

So the delete moves no stamp the query reads, and T078 needs its decision: a removal that
changes what a device renders is seen by the head only once a regenerate moves that
device's checksum, and a mark between the removal and the regenerate is not refused.

### 8.18 What each candidate reader sees of the removal (T079, 2026-10-17, read-only)

In the same test, beside §8.17's readings and on its branch, with nothing written but
§8.17's own writes and no `DiffUpdate`. The SDL is the committed `schema/infrahub.graphql`
(`make sdl`'s output, 1.11.2).

1. **Infrahub's event log**: the GraphQL root `InfrahubEvent(limit, offset, level,
   has_children, event_type, event_type_filter, primary_node__ids, related_node__ids,
   parent__ids, since, until, branches, account__ids, ids, order)`, answering `Events {
   count edges { node: EventNodeInterface } }`, each node `id event branch account_id
   occurred_at level primary_node { id kind } related_nodes has_children parent_id`, and
   `NodeMutatedEvent` adding `attributes { name action value value_previous }` and
   `relationships { name action peer { id kind } }`. A read, no write. `limit` above 50 is
   refused (`The parameter 'limit' can't be above 50`), so a branch's whole history is
   paged. `branches: [<branch>]` with `since: <branched_from>` bounds it to the branch and
   to after its creation (`since` took `branched_from`'s `Z` layout and the stamps'
   `+00:00`), and it answers the same through `/graphql/main` and `/graphql/<branch>`.
   - Before the delete it counted 105 events since `branched_from` (the seed's
     `node.created`/`node.updated`, `group.member_added`, `artifact.created`), 112 after.
   - **The delete appears**: `infrahub.node.deleted`, branch the test's, level 0, primary
     node `NetworkLink` (the deleted id), relationships `endpoints` `REMOVED` twice and
     `member_of_groups` `REMOVED` twice (two `CoreGraphQLQueryGroup`), at `occurred_at`
     `13:55:09.031152`, between the mutation's send and its return (`…08.922043`,
     `…09.034750`). Six child events follow it within 20 ms: `node.updated` on each endpoint
     `NetworkInterface` (level 1, `link` `REMOVED`), `node.updated` on the two query groups
     (level 1) and two `group.member_removed` (level 2).
   - **Pinned at its stamp the removal is already read**: the branch pinned at the
     deletion's `occurred_at` −1 µs, at it and +1 µs reads 2 links, so the graph's own stamp
     of the removal precedes the event's, and a head pinned one microsecond after the latest
     intent event would read it. The last child event's stamp ±1 µs reads 2 links too.
   - The generate after it adds 12 more: `node.updated` on two `CoreArtifact`
     (`storage_id` and `checksum` `UPDATED`), two `artifact.updated`, and query-group and
     membership events, the latest after the checksums' stamps.
   - The primary node's `kind` is the concrete kind (`NetworkLink`, `NetworkInterface`),
     never a Fylgja generic, and the log holds Infrahub's own churn (query groups,
     artifacts) beside intent, so a reader of intent's latest change would map each kind
     through the schema's `used_by`, as conformance does. One page took 0.11–0.29 s.
2. **The diff tree**, `DiffTreeSummary(branch:)` and `DiffTree(branch:)` read before and
   after, no `DiffUpdate`. The proposed change's creation had computed it: `from_time`
   `13:54:10.452384` (= `branched_from`), `to_time` `13:54:36.282687`, `num_added` 123,
   `num_updated` 10, `num_removed` 0, `num_untracked_diff_changes` 0; `DiffTree`'s 21 nodes,
   the three `NetworkLink` `ADDED` with `last_changed_at` their creation. **After the
   delete, nothing in it moved but one count**: `to_time`, `num_removed` 0 and every node's
   `last_changed_at` as before, the deleted link still listed `ADDED`; only
   `num_untracked_diff_changes` went 0 → 46, and → 54 after the generate. That count says
   the cached diff is behind the branch, never when or by what. The two reads took
   1.3–1.8 s. **`DiffUpdate`, not run**: `DiffUpdate(context, data: {branch!, name,
   from_time, to_time}, wait_until_completion)` answers `{ ok task { … } }`; it starts a
   task that recomputes the branch's diff against its base and stores it, moving `to_time`
   to its moment (D-026 measured 3.5 s on a throwaway branch). It is a write to Infrahub.
3. **An unpinned read against the head's read**, the product's own `FylgjaLink` selection
   with no `at` and pinned at `stages.HeadAt(Latest)` (`13:54:23.955206`): 2 links against 3,
   differing by exactly the deleted link (n1:ethernet-1/1 — n2:ethernet-1/1); 0.10 s and
   0.13 s for the links alone, against 0.33–0.49 s for a whole `Stamps` read. The difference
   carries no stamp: it says the head misses something and cannot say where a head that
   reads it would be pinned.

**What each would need.** (1) The event log: a fourth named root in the read-only test,
`InfrahubEvent`, with Constitution III amended and a decision entry beside D-026, which
rejected the log as following's trigger; no write, and its `occurred_at` places a head
after a removal. (2) The diff tree: a named root too (`DiffTreeSummary`), and its counts
and times move only after `DiffUpdate`, a write, so the read-only principle amended as
well; without the write it gives `num_untracked_diff_changes` alone, which has no stamp.
(3) The compare: neither a new root nor a write, the queries being Fylgja's own, but a
second read per head and no stamp, so it could refuse or warn of a head that misses a
change and could not place one after it; a design the plan never weighed.


### 8.19 The head and the staleness rule read the branch's events (T078, 2026-10-17)

Built as [D-048](../../docs/decisions.md#d-048) decides: `(*intent.StageReader).IntentEvents`
reads `InfrahubEvent(branches: [<branch>], since: <branched_from>, order: DESC, limit: 50)`
on the default branch's endpoint, pinned to nothing, newest first, and stops at the first
page that reaches an event no later than what the read needs; the head is pinned one
microsecond after the later of the latest stamp and the latest intent event, and a device
is stale when an intent event naming it, no later than the stage's `at`, is later than its
generation stamp. Three readings decided how, no twin booted:

1. **The log holds nothing of the fixture.** Read-only, `InfrahubEvent(branches:
   ["fylgja-fixture"], since: "2026-10-08T05:47:52.538186Z")` counts 0. Unfiltered it
   counted 8456 events, the oldest a `branch.created` at `2026-10-13T16:48:04.939107`; the
   fixture was seeded on 10-08, so its history predates what this install's log keeps (the
   SDL's `since` "defaults to 180 days back"). A branch whose history the log lacks reads no
   event, and its head and staleness are the stamps' alone, as before D-048.
2. **Infrahub's own churn is written on intent's own kinds.** The log outlives a deleted
   branch: §8.17's (`fylgja-test-st-1792245248-1945`) holds 124 events. Beside the seed's
   creations and the delete, each `NetworkDevice` has `node.updated` (level 1) changing
   `artifacts` alone as its artifact was created (`13:54:22.418`–`.522`, before its
   checksum), and `member_of_groups` alone, ADDED at `13:54:27.731`–`.947`, about four
   seconds after every checksum (`13:54:23.623`–`24.023`), and REMOVED at
   `13:55:32.538`–`.691`, three seconds after the regenerate's (`13:55:29.618`–`.632`): the
   query groups' membership, which Infrahub rewrites after each generation. Each
   `NetworkInterface` (18 ADDED, 2 REMOVED), `NetworkLink` (6) and `NetworkPlatform` (3)
   has the same. The schema endpoint lists `member_of_groups` and `subscriber_of_groups`
   (kind `Group`) and `profiles` (kind `Profile`) on each Fylgja generic itself, and a
   device kind's `artifacts` comes from `CoreArtifactTarget`. So the kind alone would count
   the churn as intent, every device stale after every generation and the head after it,
   and D-048's "a regenerate clears it" would never hold. The reader therefore counts a
   node's own write (`NodeMutatedEvent`) of a kind implementing a Fylgja generic when it
   creates or deletes the node, or changes a field the stamps fold into a device's intent
   (R-07): `FylgjaDevice`'s `name`, `role`, `site`, `platform` and `interfaces`;
   `FylgjaInterface`'s `name`, `iftype`, `mgmt_only`, `enabled`, `link`, `parent` and
   `device`; `FylgjaLink`'s `endpoints`; `FylgjaPlatform`'s `vendor`, `nos` and `version`.
   `addresses` and `model` stay out of the events as R-07 and T076 keep them out of the
   stamps. The query selects the names of the attributes and relationships each update
   changed (`attributes { name }`, `relationships { name peer { id } }`).
3. **The log lags its writes.** In the tier-2 proof's first run
   (`fylgja-test-st-1792250101-4999`), the delete was sent at `15:15:58.183305` and returned
   at `15:15:59.184945`; its own event's `occurred_at` is `15:15:59.182758`, before the
   return, and its six child events' `15:15:59.189406`–`.207823`, after it. A head read
   that began about half a second after the return (after a mark's write, stamped
   `15:15:59.718423`) was pinned at `15:15:59.198034`, one microsecond after n2's interface
   event, n1's (`.199256`) not yet in the log; the next read, moments later, at
   `15:15:59.199257`. The log is ordered strictly by `occurred_at`, but an event lands in it
   some time after that stamp, and the time varies: in the whole tier's run
   (`fylgja-test-st-1792250971-6537`, the other packages' tests beside it) a head read about
   half a second after the return, and the plan's own a moment later, held none of the
   delete's events, so the head stayed the stamps' and compiled, while the staleness read of
   the mark after the delete, a few seconds later, held them all and refused it; on an idle
   host (`fylgja-test-st-1792251216-8309`) the head first passed the delete 6.6 s after the
   return. So a head read before the delete's events land is the stamps', before the
   delete, and one read after it is past it; the staleness rule compares each event's
   `occurred_at` with the stage's `at`, so a mark is judged by the events whenever they
   land, and the delete names both endpoints by its peers, so neither endpoint waits for a
   child event. The tier-2 proof waits, up to 30 s, for the head to pass the delete and
   settle before it marks and plans.

**The tier-2 proof**, `internal/stages`' `TestStagesSeeARemoval`, second run
(`fylgja-test-st-1792250248-8874`, 93.2 s, before the wait above): its own seeded branch and draft proposed change,
the validators awaited (36 s); `seeded` marked at `15:18:19.837832`; the link n1:ethernet-1/1
— n2:ethernet-1/1 deleted by `DeleteLink` (`NetworkLinkDelete`), sent `15:18:21.691782`,
returned `15:18:21.936150`, moving neither `Latest` nor any device's intent stamp; `removed`
marked at `15:18:22.413029`. The head moved from `15:17:42.940186` (the stamps') to
`15:18:21.952665`, one microsecond after n1's interface event, and stayed there. `stage
plan` (7.5 s): the branch point refused `contract.node.missing` (R-04), `seeded` compiled
with 3 links, and `removed` and the head each refused `stage.artifact.stale` for n1 and n2
alone, each message naming `infrahub.node.updated of a NetworkInterface` beside the
device's own latest stamp (`its intent on … was written at 15:18:21.952664+00:00 (Infrahub's
event log: infrahub.node.updated of a NetworkInterface; its latest stamp
2026-10-17T15:17:36.296836+00:00), later than its artifact device-config was generated (…)`).
A generate then moved n1's and n2's checksums, the head went back to the stamps' (the
checksums later than every intent event, the churn after them not intent), and the plan
(6.2 s) compiled the head with 2 links and still refused `removed` for n1 and n2, its
artifacts at its `at` those it read. The cleanup deleted 2 stages, 1 proposed change and the
branch.

With the wait for the log (item 3) the proof passed twice alone (93.4 s and 100.4 s, the
head first past the delete 6.6 s after its return in the second), and then inside **tier 2
whole**, `make test-contract`, passed in 716.7 s (`internal/stages` 712.1 s, `internal/stage`
482.8 s, `internal/intent` 212.9 s), every package passing; the whole tier's run before the
wait (706.1 s) had failed this test alone, for the lag. Infrahub was left with `main` and
`fylgja-fixture` alone, no proposed change and no stage, and `clab inspect --all` found no
container. No golden, no fixture id and no format version moved.

### 8.20 Tier 3 on the tree that carries D-048 (T080, 2026-10-17)

From the repository root with `local/.env`'s names in the environment, after `make build`
and the worker and the API's server restarted from this tree (16:10Z; both had read
`(deleted)` since T078) and verified as `CLAUDE.md` says: each binary current,
`INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN` in the environment,
both reports naming both packages with their logins set, the server `listening on
127.0.0.1:7650 (API version 1, build 0.1.0-dev)`. The dev server answered `SERVING`.
Before: no lab, no twin directory, no Schedule, `Branch` `main` and `fylgja-fixture`,
`CoreProposedChange 0`, `FylgjaStage 0`; `free -m` 18.6 GiB available, a load average of
1.5, no tier 2 beside it.

- **`make test-e2e`** (16:10:27Z–16:30:27Z): **`E2E-OK`**, exit 0, wall **1198.9 s**
  (19 m 59 s), against §8.11's 1125.5 s and T076's 1159.1 s. Case 1 deployed `47b2c449…`.
  Case 7: seed 19.7 s, the draft proposed change and its three validators 51.1 s, n1's and
  n3's artifacts moved and Ready 7.7 s after the generate returned, the plan 10.3 s (exit 1:
  four stages, the branch point on `main` refused `contract.node.missing` with no id,
  `seeded`, `third-link` and the head compiled to three ids, `977689e5…`, `d5cfeecc…` and
  `4bd5717e…`; one link added, n1 and n3 changed; the step from `third-link` to the head
  computed `unchanged`), the create from `seeded` 55.8 s deploying the id the plan printed
  for it, the step to `third-link` 16.0 s and the `unchanged` step to the head 12.1 s
  (command wall), destroy 2.3 s. The head's `at` (`16:22:21.282346`) is earlier than
  `third-link`'s written `16:22:22.158789`, as in §8.11, and the head still planned last.
  Case 8: proposed change 40.5 s, create 87.2 s, the step to `mixed-link` refused
  `step.restart.required` naming e1 (dry run and run), then taken with `--allow-restart` in
  83.3 s (e1 restarted in place, s1 and e2 untouched, the link seen from both ends 0.7 s
  and 0.6 s after), the step back with `--stage <b>/seeded` 72.2 s, the waits settled after
  4.575 s and 3.587 s. Creates 42.7–91.5 s; verify 4.3 s, 3.8 s and 2.5 s; the boot half
  8.3 s and 6.9 s.
- **Why the head did not move**, read-only after the run, since the log outlives a deleted
  branch (§8.19, item 2): `InfrahubEvent(branches: [<case 7's branch>], since:
  16:22:12Z, until: 16:22:24Z)` holds 11 events. The add-link's seven, intent's by D-048
  (two `NetworkInterface` created, their two devices' `interfaces`, the `NetworkLink`
  created, its two endpoints' `link`), occurred at `16:22:13.320990`–`.502911`, after
  `seeded` was marked (`16:22:12.808310`) and before the generate; the other four are the
  two artifacts' (`CoreArtifact` `storage_id` and `checksum`, `16:22:21.116143` and
  `16:22:21.322734`, with their `artifact.updated`), which are not intent. So the latest
  intent event precedes the branch's latest stamp, a checksum at `16:22:21.282345`, and
  the head is that stamp plus one microsecond, as before D-048.
- After: `clab inspect --all` `{}`, no `local/twin`, no Schedule and no running workflow,
  `Branch` `main` and `fylgja-fixture`, `CoreProposedChange 0`, `FylgjaStage 0`. The worker
  and the server were left running on this tree's binary. No case failed, so nothing was
  fixed. No golden, no fixture id and no format version moved.
