# Contract: the stage reference and its resolution

How a stage is named on the command line and in the findings document, how a reference
resolves to a pinned `(branch, at)`, and every rule the resolution makes, with its
severity, exit status, step, object and wording. Identifiers, exit statuses and the JSON
blocks are the contract; wordings are quoted where a test pins them and illustrative
otherwise. [research.md](../research.md) R-05–R-08, R-15, R-16.

## The reference

```
<branch>/<label>
```

- Split at the **first** `/`. The branch is `^[^/\s]+$`, the label `^[^/\s]+$`
  (`stages.BranchPattern`, `stages.LabelPattern`; the label's equals the kind's regex,
  held by a test). So a reference is one shell word.
- `branch-point` and `head` are reserved labels, naming the two derived stages. A mark the
  operator labelled either is refused (`stage.label.reserved`).
- `stages.Form` is how a refusal names the syntax: `<branch>/<label>, a branch with no "/"
  and no whitespace and a label with neither`. `stages.BranchForm` is the branch's half,
  used by `stage list --branch` and `stage plan --branch`.
- `String()` is `branch/label`. In text a derived stage prints as `b/branch-point` and
  `b/head`.

## The resolution, in order

`stages.Resolve(ctx, reader, client, ref, now)` and `ResolveFrom` for a listing already
read. Each step's refusal ends it; every refusal is a rejection at step `resolve` (none for
`intent read`, whose operations carry no step), exit 1 unless said, and is made before any
run starts and before any branch's intent is read: the stamps read (step 6, 8, 9) reads
stamps and never a value of intent, and the event read (steps 6 and 8) Infrahub's record of
writes.

| # | What is read | Refusal | Object | Wording (shape) |
|---|---|---|---|---|
| 1 | `GET /api/schema` on the default branch: `FylgjaStage` with `label`, `as_of`, `description` and `proposed_change`; `CoreProposedChange.fylgja_stages` | `stage.kind.absent` | `FylgjaStage` | `the default branch's schema has no kind FylgjaStage: load schema/fylgja-stage.yaml on it; only --stage, stage list and stage plan need it` / `kind FylgjaStage on the default branch lacks the attribute(s) …, which this build reads: load …` / `kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds: load …` |
| 2 | `CoreProposedChange(state__value: "open", source_branch__value: <branch>)` with `fylgja_stages` | `stage.unknown` | the branch | `no open proposed change has source branch b; the branches with one are: x, y` or `…; there is no open proposed change` |
| 3 | `Branch(name: <branch>)`: `branched_from`, `created_at` | `stage.unknown` | the branch | `branch b does not exist; the open proposed change <id> still names it (Infrahub cancels it about sixteen seconds after a branch is deleted)` |
| 4 | the stage by label among the branch point, the marks and the head | `stage.unknown` | the reference | `proposed change <name> (<id>) on branch b has no stage "x"; its stages are: branch-point, seeded, third-link, head` |
| 4 | two marks of the proposed change share the label | `stage.duplicate` | the reference | `stage b/x is held by 2 objects (ids …), which the kind's uniqueness constraint should have refused; none is chosen` |
| 4 | the mark's label is `head` or `branch-point` | `stage.label.reserved` | the reference | `stage b/head is a mark labelled "head", which names the derived head of every proposed change and is reserved; relabel it (schema/README.md); the head of b is still its derived stage` |
| 5 | the mark's `at`: `as_of` verbatim, else `label.updated_at` | `stage.at.unresolved` | the reference | `stage b/x has no at: no as_of is written on it and Infrahub returned no updated_at for its label, so it names no point in time` |
| 5 | more than six fractional digits | `intent.at.precision` (exit 2) | the reference | M1's sentence, then `Write the stage's as_of with at most six.` |
| 5 | a given `as_of` later than the server's clock, read once and never sent | `stage.at.unresolved` | the reference | `stage b/x has at … (given), later than the current time …: it seals nothing yet, and a twin from it could differ between two creates` |
| 6 | the head: the branch's unpinned stamps (`Stamps`) and its intent events after the latest of them (`IntentEvents`, below); `at` = the later of the latest stamp and the latest event's `occurred_at`, + 1 µs | `operation.failed` (exit 2) only when Infrahub cannot be read | — | the read's own wording |
| 7 | the `at` against `branched_from` and `created_at` | `stage.at.before_branch_point` | the reference | `stage b/x has at …, before the branch point … of b: a rebase at … moved the branch point past it (the branch was created at …); mark the stage again, or delete it` when `created_at < at < branched_from`; `… before the branch point … of b, and before the branch was created at …; a stage names a moment on its source branch` otherwise |
| 8 | the staleness rule at the stage's `at` (below) | `stage.artifact.stale` (one per device) | `<device>` | `device n1: its intent on b was written at …, later than its artifact device-config was generated (checksum stamped …; the proposed change's artifact validator last completed …): stage b/x was marked before the artifacts were regenerated; regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the proposed change's checks: a retry in Infrahub, or CoreProposedChangeRunCheck) and mark again`; `its checksum unstamped` in place of `checksum stamped …` when the checksum carries no stamp, and `no artifact validator of the proposed change had completed` in place of the validator's clause when none had; the tail after the colon by the kind of stage, the head's `the head of b is later than the artifacts' last regeneration; regenerate (…)` and the branch point's `stage b/branch-point reads main as it was at the branch point, before its artifacts were regenerated` in place of the mark's; when an event is later than the device's stamps, `written at <occurred_at> (Infrahub's event log: infrahub.node.updated of a NetworkInterface; its latest stamp …)`, or `no stamp of its own` in place of `its latest stamp …`, in place of `written at …` |
| 9 | `main`'s unpinned stamps against `branched_from` | `stage.main.moved` (warning) | the branch | `main has moved since b's branch point: its latest write is …, the branch point …; the branch point stage still reads main as it was then, and nothing is refused` |

The branch point's `at` is `branched_from` verbatim (step 3) and its read is on `main`;
steps 5 and 7 cannot refuse it. The head's `at` (step 6) is after every stamp and every
intent event by construction, so step 7 cannot refuse it either; step 8 can (the head is
stale after an intent edit, a removal included, until a regenerate or a run-check).

**At `start`**, before any connection, exit 2: `stage.ref.invalid` (`--stage "x" is not a
stage reference: expected <branch>/<label>, …`; `--branch "a/b" is not a branch: expected
a branch with no "/" and no whitespace`) and `stage.flags.conflict` (`--branch is
meaningless with --stage: a stage is a whole pinned reference (branch and at)`; `--at` the
same; `--interval is meaningless with --stage: a stage twin is pinned and never follows`;
the first conflicting flag, in the order `--branch`, `--at`, `--interval`).

**A listing** (`stage list`) applies steps 1–6 and 9 to every open proposed change's stages
and refuses nothing but step 1; a reserved label is a rejection beside its row (the
document's status `rejected`, exit 1, the other rows still listed); step 3's branch gone
and step 5's stage with no `at` are warnings under their own identifiers and wordings, every
stage still listed (the gone branch's message adds `; until then its branch point and head
have no at`); an orphaned stage
(`FylgjaStage(proposed_change__isnull: true)`, a stage removed from its proposed change's
`fylgja_stages`; [D-047](../../../docs/decisions.md#d-047)) is the warning
`stage.orphaned` (object the stage's id, `stage "<label>" (id …) names no proposed change:
it was removed from its proposed change's fylgja_stages; delete the stage`). **A plan**
applies every step to every stage and goes on.

## Stamps

`(*intent.Client).Stamps(ctx)` on the client's branch at its `at` (empty for the head's
and `main`'s unpinned reads):

```graphql
fragment ArtifactStamps on CoreArtifactTarget {
  artifacts { edges { node { name { value } checksum { value updated_at } } } }
}
fragment PlatformStamps on FylgjaPlatform {
  vendor { value updated_at } nos { value updated_at } version { value updated_at } model { value }
}
query Stamps($limit: Int!, $offset: Int!) {
  FylgjaDevice(limit: $limit, offset: $offset) { count edges { node {
    id name { value updated_at } role { updated_at } site { updated_at }
    platform { properties { updated_at } node { ...PlatformStamps } }
    interfaces { edges { properties { updated_at } node {
      id name { value updated_at } iftype { updated_at } mgmt_only { updated_at } enabled { updated_at }
      link { properties { updated_at } } parent { properties { updated_at } } } } }
    ...ArtifactStamps } } }
  FylgjaLink(limit: $limit, offset: $offset) { count edges { node {
    endpoints { edges { properties { updated_at } node { device { node { name { value } } } } } } } } }
}
```

Paged as `Devices` is. A `null` `properties.updated_at` (an unset relationship) is
skipped, as is any other `null` stamp. The platform's values pick the device's package; its
`vendor`, `nos` and `version` are stamped because they reach the artifact (the template
renders them into every device's configuration and branches on `nos`) and `nos` the
bundle, and `model`, which reaches neither, is read but not stamped. The device's and its
interfaces' `id`s are how an intent event names the device (below). Every stamp is
compared parsed (RFC 3339); none is ever sent but the head's `at`.

## Events

A removal (a link or an interface deleted, a relationship unset) moves no stamp above
(research §8.17), so the stage reader also reads the source branch's event log
([D-048](../../../docs/decisions.md#d-048); Constitution III 1.3.0),
`(*intent.StageReader).IntentEvents(ctx, branch, since, after)`, on the default branch's
unnamed endpoint, pinned to nothing:

```graphql
query IntentEvents($branch: String!, $since: DateTime!, $limit: Int!, $offset: Int!) {
  InfrahubEvent(branches: [$branch], since: $since, order: DESC, limit: $limit, offset: $offset) {
    count edges { node { event occurred_at primary_node { id kind }
      ... on NodeMutatedEvent { attributes { name } relationships { name peer { id } } } } } }
}
```

`since` is the branch's `branched_from`, verbatim, which keeps out an earlier branch of the
same name (the log keeps a deleted branch's events). Paged at 50, Infrahub's limit, newest
first, stopping at the first page that reaches an event no later than `after`: the latest
stamp for the head, the earliest checksum the staleness rule judges for a stage ("" reads
every page, when a checksum is unstamped). One read serves every stage of a resolution or a
plan: a read down to an earlier bound serves a later one. An event is **intent's** when it
is a node's own write (`NodeMutatedEvent`) whose primary node's kind is in the `used_by` of
one of the four generics on the branch's schema (`GET /api/schema?branch=`, read once and
only when an event is to be mapped), at any level, and it is `infrahub.node.created` or
`infrahub.node.deleted`, or an update changing one of the fields the stamps fold into a
device's intent: `FylgjaDevice`'s `name`, `role`, `site`, `platform`, `interfaces`;
`FylgjaInterface`'s `name`, `iftype`, `mgmt_only`, `enabled`, `link`, `parent`, `device`;
`FylgjaLink`'s `endpoints`; `FylgjaPlatform`'s `vendor`, `nos`, `version`. Infrahub's own
churn is never intent: an artifact's, a group's or a branch's event, the stage kind's, and
an update of a node's `member_of_groups` or `artifacts` alone, which Infrahub writes on
every device, interface, link and platform seconds after each generation (research
§8.19). The concrete kind is read only to be mapped and to be named in a message, and is
never queried. An event **names** a device when the device's `id`, or one of its
interfaces' `id`s as `Stamps` read them at the stage, is the event's primary node or the
peer of one of its relationships. An event lands in the log a few seconds after its write,
a varying time (research §8.19): a head read before a removal's events land is the stamps'
and does not see it yet, while a mark is judged by each event's `occurred_at` against its
`at` whenever the event lands. A branch whose history predates what the log keeps (on this
install, `fylgja-fixture`) reads no event.

**The head's `at`**: the later of the latest over every stamp above and the latest intent
event's `occurred_at`, plus one microsecond, formatted `2006-01-02T15:04:05.000000-07:00`
(Infrahub's own layout: `2026-10-08T05:48:38.544483+00:00`).

**The generation stamp of a device at a stage**: the later of (a) its artifact's
`checksum.updated_at` in `Stamps` pinned at the stage's `at`, the artifact named by the
device's package's `config.artifact_name`, and (b) the proposed change's artifact
validator's `completed_at` **value**, from `CoreArtifactValidator(proposed_change__ids:
[id]) { edges { node { completed_at { value } } } }` on the default branch pinned at `at`
(absent when none has completed; several validators, one per definition, take the latest).
Its value is read, never its `updated_at`: pinned, the value is the one in force and the
metadata the current one (research §6.5).

**A device's intent stamp** at the stage: the latest over its own `name`, `role`, `site`,
its `platform` edge and its platform's `vendor`, `nos` and `version`, each interface's edge
and `name`, `iftype`, `mgmt_only`, `enabled`, its `link` and `parent` edges, and every
`endpoints` edge of a link whose endpoint's device is this one. A platform edited on the
branch so moves the intent of every device on it, and of no other (T076).

**When a device's intent was written** at the stage: the later of its intent stamp and the
`occurred_at` of the latest intent event that names it and is no later than the stage's
`at` (none for the branch point, read on `main` before the branch's history).

**Stale**: intent written later than the generation stamp. Fresh otherwise. A device with
no artifact of its package's name at `at` is left to the read (`artifact.missing`).

## The future rule and the clock

The server reads its clock once per resolution, compares it with a **given** `as_of` only,
and never sends that reading or compares it with a stamp Infrahub returned (D-032's rule,
kept by D-045).

## Where each refusal is made

| Command | Steps run | Where |
|---|---|---|
| `stage list` | 1–6, 9; orphans | the server, before anything else |
| `stage plan` | 1–9 per stage | the server, before each stage's read |
| `twin create --stage`, `intent read --stage` | 1–9 | the server, at `resolve`, before the run and before the dry run |
| `twin step [--stage]` | 1–3 once; the target's 4–9 | the server, after the host is read and the target chosen, before the from bundle, the host check and containerlab's plan |
