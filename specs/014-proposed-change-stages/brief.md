# Specify brief: 0.2 feature 1 of 3: a proposed change's stages

This is what `/speckit-specify` reads for the pass that replaces waypoints with stages,
the first of the roadmap's [Next section](../../docs/roadmap.md#next). It was written on
2026-10-16 from a design session with the operator, after a probe against the running
Infrahub 1.11.2 ([Verified live](#verified-live)). It supersedes
[D-032](../../docs/decisions.md#d-032) and reshapes what M10 built. The rehearsal
([015](../015-proposed-change-rehearsal/brief.md)) reads what this pass builds. Specify what
the operator gets, not a new design. [References](#references) names every file to read.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/014-proposed-change-stages. 0.2, the first of its three features: a proposed change's stages in place of waypoints, as docs/roadmap.md's Next section defines it. Read specs/014-proposed-change-stages/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Why

The operator found waypoints clumsy in two ways:

- **They are not Infrahub-native.** A waypoint is Fylgja's concept bolted on beside
  Infrahub, and nothing in Infrahub knows it.
- **They are separate from the change.** A waypoint is a branch-agnostic side object that
  names a branch by free text, outlives it, and is invisible where the schema lacks the
  kind.

The session looked for a native home ([Verified live](#verified-live), and the research
summarised there):

- Infrahub 1.11.2 has no named point in time: no branch tags, checkpoints, snapshots or
  saved time-travel views. The time selector writes an `at` URL parameter and saves
  nothing.
- `Branch` is not a schema kind, so nothing can relate to it. Its only free text is its
  description.
- Events are kept for 7 days, and nothing fires when a branch's artifacts are all Ready.
- No issue on any OpsMill repository asks for named points in time.
- **The proposed change** is Infrahub's own unit of change. It is branch-agnostic, a user
  kind may relate to it, and it can be opened as a draft while the change is built.

So a stage is a moment *of a proposed change*.

## Where the shape is fixed

- **[D-032](../../docs/decisions.md#d-032)**, superseded here, and what it was built on:
  a pinned reference read rather than composed; the operator writes and Fylgja reads; an
  absent `at` is the write stamp Infrahub returns; the name is not provenance.
- **[D-036](../../docs/decisions.md#d-036)**: stepping, divergence, `--allow-restart`.
  Its target becomes a stage of the twin's own proposed change.
- **[D-012](../../docs/decisions.md#d-012)**: the intent reference `(branch, at?)`. A
  story along `main`'s own history stays `--branch main --at`.
- **[D-028](../../docs/decisions.md#d-028)**: Fylgja's schema loads on `main`, the kind
  beside the contract included.
- **[Constitution 1.1.1](../../.specify/memory/constitution.md)**:
  - **III**: every operation Fylgja makes on Infrahub is a query.
  - **VI**: Fylgja sends no `at` of its own. The branch point is an Infrahub stamp read
    rather than composed, as a waypoint's write stamp was.
  - **IX** and **X**.

<a id="verified-live"></a>
## Verified live, 2026-10-16 (Infrahub 1.11.2)

A probe on a throwaway branch `fylgja-test-stage-probe`, with a draft proposed change, run
twice: once for the data, and again for the operator to look at the UI.
The candidate kind it loaded is
[research-probe/fylgja-stage.yaml](research-probe/fylgja-stage.yaml). Everything was
deleted after, and `main`'s schema hash read `0aba31a5…` before and after.

- **The kind and its extension load on a branch.** A branch-agnostic `FylgjaStage` with a
  required `cardinality: one` relationship to `CoreProposedChange`, plus an `extensions`
  entry giving `CoreProposedChange` the reverse `fylgja_stages` with the same identifier,
  passed `schema/check` (202, no warnings) and `schema/load` (200).
- **A human-friendly id through the proposed change is refused**: `HFID of FylgjaStage
  refers to peer CoreProposedChange with a non-unique combination of attributes
  ['name__value']`. A proposed change's name is not unique, so a stage cannot be named
  through it, and a proposed change is found by its source branch (one open proposed change
  per branch).
- **A draft proposed change** (`is_draft: true`) was created, and two stages were written
  related to it. Both read back **in both directions** on the branch: each stage names its
  proposed change, and the proposed change lists its stages.
- **An absent `as_of`** reads `null`, with the attribute's own `updated_at` as its write
  stamp, as a waypoint's did. A given `as_of` is kept as written.
- **`order_by: [as_of__value]`** listed the stage with a given time first and the null one
  after.
- **The proposed-change view does not show stages.** The operator saw nothing of them on
  it. Its overview renders a fixed set of fields (`proposed-change-details.tsx`), with no
  section for related objects.
- **A proposed change has no generic object page**: `/objects/CoreProposedChange/<id>`
  redirects to the branch's home page.
- **A stage's own page works.** The kind is in the sidebar ("Stage"), and the page's
  breadcrumb carries a dropdown that switches between stages. With one proposed change it
  could not tell whether it lists the kind's stages or only that proposed change's.
- Not tried: the uniqueness constraint `[proposed_change, label__value]` refusing a
  duplicate; the kind on `main`.

## What changes, and nothing else

1. **`FylgjaStage`**, loaded on `main` beside the contract (`schema/fylgja-stage.yaml`).
   - It is branch-agnostic.
   - It has a required relationship to the proposed change it belongs to, a `label`
     unique within that proposed change, an optional `as_of`, and an optional description.
   - It is ordered by `at`.
   - An extension gives `CoreProposedChange` its stages.
   - It has no branch attribute: its branch is its proposed change's source.
2. **A proposed change's stages**, as Fylgja reads them, in this order:
   - the source branch at `branched_from`;
   - each `FylgjaStage` in order of `at` (an absent `as_of` is the write stamp);
   - the branch's head, read unpinned.

   It warns when `main` has moved since the branch point. It refuses a stage whose `at` is
   before the branch point or later than now.
3. **The commands.** `--stage` replaces `--waypoint` on `twin create`, `twin step` and
   `intent read`. `stage list` and `stage plan` replace `waypoint list` and `waypoint
   plan`, naming the proposed change by its source branch. `twin step` goes to a stage of
   the twin's own proposed change. The findings' `waypoint.*` rules become `stage.*`.
4. **`FylgjaWaypoint` is removed**, with its commands, rules, contract
   (`waypoints.schema.json`), the fixture tool's `-waypoint` and test support's series. The
   twin record names a stage where it named a waypoint.
5. **Tier 3's cases 7 and 8** make a throwaway branch and draft proposed change with
   stages, where they made a throwaway series. The README's stepping walk-through does the
   same. The recording is remade at `v0.2.0`.
6. **The records.**
   - The decision entry superseding D-032.
   - The schema README ("Stages: marking one").
   - The contracts and the formats they move (twin record, API, CLI).
   - The architecture and its C4 model, the glossary, development.md and
     verified-facts.md ([Verified live](#verified-live)).
   - `docs/ideas.md`'s persistent fixture series, closed.
   - `CLAUDE.md`'s Formats and State.

## Decided

- **A stage belongs to a proposed change.** It relates to it, and its branch is the
  proposed change's source, so there is no free-text branch. A proposed change can be
  opened as a draft while the change is built, and stages are marked on it.
- **The ends are derived, not marked.** The first stage is the branch point and the last
  is the head, so a proposed change with nothing marked has two stages. Only the moments in
  between are written.
- **The operator writes stages; Fylgja only reads them** (Constitution III), by
  Infrahub's own means: the UI, an object file, `infrahubctl`.
- **A story along `main`'s own history keeps no named marks.** It is `--branch main --at`,
  as before waypoints. A proposed change cannot have `main` as its source.
- **Waypoints are removed, not kept beside stages.** Fylgja is 0.x, and two ways to name a
  pinned reference would split every command.
- **No human-friendly id**: Infrahub refuses one through the proposed change's
  non-unique name.
- **Infrahub's proposed-change view will not show stages.** 015's comment lists them on
  the proposed change, and the upstream request ([Left to the plan](#left-to-the-plan))
  asks Infrahub for a native mark.
- **Out of this feature**: the rehearsal and the checks (015), probes (016), deriving
  intermediate stages from Infrahub's history (a later probe: an artifact regeneration
  marks a stage done, but a regeneration to identical bytes leaves no trace).

## Open, for clarify

1. **How a stage is named on the command line.** `<branch>/<label>`; `<branch>/<n>` by
   position, with `0` the branch point and the last the head; or both.
2. **A proposed change that is merged or closed.** Are its stages still listed and
   creatable (reading its source branch while it exists), or refused?
3. **A twin created from the head.** The head is read unpinned, so a twin from it is not
   reproducible: is that allowed, with the record saying so, or must the operator mark a
   last stage to pin it?

## Left to the plan

- **Live verification**, recorded in research.md and then verified-facts.md:
  - the uniqueness constraint's refusal;
  - the kind and the extension loaded on `main`;
  - what a read pinned at exactly `branched_from` returns (the decision log's open question
    on reads before a branch existed), and the same after a rebase moves it;
  - how a branch's being behind `main` is read.
- **The kind**, written from [the probe's candidate](research-probe/fylgja-stage.yaml)
  after the plan loads OpsMill's `infrahub:infrahub-managing-schemas` and `-objects`
  skills.
- **The twin record's format bump**, and the frozen copies older tests read.
- **The upstream request** for named points in time, through OpsMill's
  `infrahub:infrahub-reporting-issues` skill, once this pass works: a draft for the
  operator's approval, citing [#10592](https://github.com/opsmill/infrahub/issues/10592)
  (named diffs advertised but unusable), [#10589](https://github.com/opsmill/infrahub/issues/10589)
  (`at` used to pin a query set) and [#1045](https://github.com/opsmill/infrahub/issues/1045)
  (branch metadata).
- **The decision entry superseding D-032**, written after the verification.

## Exit

- **Tier 1**: the stage list (ends derived, order, refusals, warning), `--stage` parsing,
  the step's target rule, the record.
- **Tier 2**: the kind on `main`; a throwaway branch and draft proposed change with two
  stages listed and planned against the real Infrahub; each refusal; no `FylgjaWaypoint`
  left on `main`.
- **Tier 3**: cases 7 and 8 on stages, `E2E-OK`; after the tier, no `fylgja-test-*`
  branch, proposed change or stage remains.
- **Owed before the work starts**: nothing.

<a id="references"></a>
## References

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Next](../../docs/roadmap.md#next), [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope and the decisions owed |
| [docs/decisions.md](../../docs/decisions.md): D-012, D-028, D-032, D-036, the [open questions](../../docs/decisions.md#open-questions) | what this pass supersedes and keeps |
| [schema/fylgja-waypoint.yaml](../../schema/fylgja-waypoint.yaml), [schema/README.md](../../schema/README.md) | the kind and guide this pass replaces |
| [contracts/waypoints.schema.json](../../contracts/waypoints.schema.json), [contracts/twin.schema.json](../../contracts/twin.schema.json), [contracts/api.md](../../contracts/api.md), [contracts/cli.md](../../contracts/cli.md) | the documents that move |
| [internal/waypoint](../../internal/waypoint), [internal/findings/finding.go](../../internal/findings/finding.go) (`waypoint.*`, `step.target.*`), [internal/cli](../../internal/cli), [internal/testsupport](../../internal/testsupport), [cmd/fylgja-fixture](../../cmd/fylgja-fixture) | what M10 built |
| [scripts/e2e.sh](../../scripts/e2e.sh) (cases 7, 8), [README.md](../../README.md), [docs/recording](../../docs/recording) | the walk-throughs and cases that move |
| [docs/ideas.md](../../docs/ideas.md): the persistent fixture series | the idea this pass closes |
