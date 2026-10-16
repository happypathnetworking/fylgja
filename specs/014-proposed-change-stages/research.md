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
> [D-045](#d-045). A regeneration to identical bytes writes no checksum and no storage id,
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
| — | `stage.orphaned` (warning) | a stage whose proposed change was deleted under it |
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
added under `https://fylgja.dev/schemas/stages.schema.json`; `findings_version` stays `1`
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
and branch, and `stage list --branch` after it is refused `stage.unknown`. Case 8 does the
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
