# Specify brief: 0.3 spec 2 of 5: snapshots, the core's one input (F-024)

This is what `/speckit-specify` reads for roadmap F-024, the second spec of
[Release 0.3](../../docs/roadmap.md#release-03). It was written on 2026-10-27 from a design
session with the operator, held after 017's close, that first considered making F-024 the
split of Fylgja into a core, a reader and an orchestrator, then scaled it back to what the
roadmap wrote on 2026-10-25: **the snapshot as the core's one input, small, since the
pieces are all in the tree**, proving the core and orchestrator seam before anything is
split. The session read the tree and the records named under [References](#references)
and verified nothing live; the plan verifies each point before relying on it. Specify
what the operator gets, not a new design.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/018-snapshots GIT_BRANCH_NAME=018-snapshots. 0.3, the second of its four specs: snapshots, the core's one input, as docs/roadmap.md's F-024 and Release 0.3 section define it. Read specs/018-snapshots/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Why

- **The core's workflows still know a branch.** `twin step` and `twin rehearse` already
  read, compile and file on the server, on `stage plan`'s path, and hand the worker a
  bundle id ([server/step.go](../../internal/server/step.go),
  [server/rehearse.go](../../internal/server/rehearse.go)). The live `twin create` does
  not: its provision workflow reads the branch as an activity, `ReadIntent`, and writes a
  temporary CTM under `bundles/.reads/` for the compile
  ([provision/workflow_provision.go](../../internal/provision/workflow_provision.go)). Until
  every workflow takes one input that is not a branch, the production shape's core, which
  knows no branch, proposed change, stage or source of truth, is a drawing.
- **The input nearly exists.** Since M5 the CTM carries each device's rendered artifact
  ([ctm/types.go](../../internal/ctm/types.go), `Artifact`), and since 017 its envelope
  carries the branch, `at`, schema hash, scope, mapping and fidelity list. The bundle store
  keeps the CTM a create read as a sidecar beside its bundle. What is missing is a hash of
  its own, a home keyed by that hash, a schema and a version, the probe slot the third spec
  fills, and commands that take one.
- **F-025 needs it to exist.** NetBox cannot replay time, so a stage there is the snapshot
  Fylgja took when the operator marked it. The snapshot's id is what addresses intent when
  the source of truth cannot, and Constitution VI has to say so before the fourth spec
  reads NetBox.

## Where the shape is fixed

- **The roadmap's [F-024](../../docs/roadmap.md#f-024)** and the
  [Release 0.3 section](../../docs/roadmap.md#release-03), written on 2026-10-25. This
  brief differed from the F-024 paragraph in two places, both settled with the operator on
  2026-10-27 and written back the same day: the snapshot *wraps* the CTM rather
  than being a new document that holds the configurations beside it, and the bundle's CTM
  sidecar is retired by the snapshot store rather than kept beside it.
- **[D-010](../../docs/decisions.md#d-010)**, the thin CTM with provenance, the contract
  since 017; **[D-057](../../docs/decisions.md#d-057)**, the CTM at `2`, which nothing
  moves again in this release. The snapshot wraps CTM 2 unchanged.
- **[D-011](../../docs/decisions.md#d-011)**, the pure compiler and the content-addressed
  bundle; **[D-023](../../docs/decisions.md#d-023)**, `observed_at` outside the hashed
  bytes. The snapshot's id follows the same rule the manifest's provenance already does
  ([compiler/manifest.go](../../internal/compiler/manifest.go), `Provenance`): the
  envelope minus `observed_at`.
- **[D-014](../../docs/decisions.md#d-014)**, the bundle store behind a small interface so
  that object storage can replace the directory at M8. The snapshot store is built the
  same way.
- **[D-012](../../docs/decisions.md#d-012)**, the intent reference `(branch, at?)`, and
  **[D-045](../../docs/decisions.md#d-045)**, a stage as the operator's mark on a proposed
  change, resolved to a pinned `(branch, at)`. Unchanged: a stage still resolves to a
  pinned read, and the snapshot is what that read produces.
- **[D-026](../../docs/decisions.md#d-026)**, following by a scheduled read and compare.
  **Untouched by this feature, on purpose**, and removed by the next one ([Hand-off](#hand-off)).
- **[D-040](../../docs/decisions.md#d-040)**, the API as the core's boundary;
  **[D-055](../../docs/decisions.md#d-055)**, the schemas' `$id` under this repository's
  URL.
- **[D-058](../../docs/decisions.md#d-058)** and **[D-060](../../docs/decisions.md#d-060)**:
  a stamp Infrahub's own account wrote is not intent's. The tier-2 proof rests on them.
- **[Constitution 2.1.0](../../.specify/memory/constitution.md)**:
  - **VI** is amended, a minor bump to 2.2.0: "Every CTM and bundle MUST record its
    provenance" becomes "Every CTM, snapshot and bundle"; `observed_at` "MUST NOT appear
    in the bundle" gains "nor in the bytes a snapshot's id hashes"; and a sentence is
    added for the fourth spec to inherit: where the source of truth cannot replay time,
    the snapshot's id addresses intent, and a stage there is the snapshot Fylgja took when
    the operator marked it. The sentence binds nothing in this feature, since Infrahub
    replays time.
  - **V**: the compiler stays pure, and is unchanged; it compiles the CTM a snapshot holds.
  - **IX**: the manifest is the provenance of what runs, and does not move.
  - **X**: the snapshot's fidelity list is the CTM's, carried whole.

<a id="the-snapshot"></a>
## The snapshot

A document of version `1`, stored and sent as JSON, with a schema in `contracts/`.

| Part | Field | Hashed | What it is |
|---|---|---|---|
| outer | `snapshot_version` | no | `1` |
| outer | `snapshot_id` | no | the hash of the body, as the manifest carries `bundle_id` |
| outer | `observed_at` | no | the UTC time the take began, as the CTM's is for a read |
| body | `ctm` | yes, minus its `observed_at` | one CTM 2, valid under `contracts/ctm.schema.json`, unchanged |
| body | `probes` | yes | a list, **empty and required in version 1**: "this intent, with no probe declarations"; 016 defines the element and bumps the version |

**The id** is the hash of the canonical body with the inner CTM's `observed_at` removed:
the hashed bytes differ from the stored bytes, as they already do for the bundle, and the
schema says so in one sentence. What stays in the hash, deliberately: `branch`, `at`,
`schema_hash`, `scope`, the `mapping` with its version, the fidelity list, every device's
artifact, and the empty `probes`. So the same stage taken twice has the same id, a branch
read with no `at` has the same id while nothing moved, and a mapping or schema change
moves it, as it already moves the bundle.

**The limits**, stated in the records and tested by nothing:

- **A rebase moves every stage's snapshot.** D-012 records that a rebase re-stamps a
  branch's whole content at the new `branched_from` and discards its earlier history from
  pinned reads. A stage resolved after its branch was rebased reads differently, or
  empty, and gets a different id. That is correct behaviour, `stage.main.moved` is its
  neighbour, and it means a snapshot id is reproducible only while the branch's history is.
- **An artifact Infrahub re-renders to different bytes** for the same data has not been
  seen and is not ruled out by anything Fylgja controls. The id would move with it.

**Snapshot and bundle.** A snapshot is the input and the bundle is the output: one
snapshot compiles to one bundle under one compiler, one PSP set and one build, and a
bundle made from a snapshot file and one made from a branch read of the same intent are
the same bundle. The snapshot id is therefore recorded beside the bundle id everywhere
but in the bundle itself.

## What changes, and nothing else

1. **The snapshot** (`internal/snapshot`, a new package): the document, its canonical
   encoding, its id, its validation (the outer fields, then the inner CTM under CTM 2's
   own validation), and `contracts/snapshot.schema.json` at version `1` with its `$id`
   under this repository's URL. Refusals mirror the bundle's three
   ([findings](../../internal/findings)): `snapshot.invalid`,
   `snapshot.version.unsupported`, `snapshot.id.mismatch`, and one the bundle has no need
   of, `snapshot.unknown`, for an id the store does not hold.
2. **The snapshot store**: `snapshots/<snapshot_id>.json` under the state root, beside
   `bundles/`, behind the bundle store's interface (`Put`, `Has`, `Path`, `Fetch`), kept
   forever as bundles are. A `Put` of an id the store holds keeps the stored document and
   writes nothing, as the bundle store does: two takes of one stage share an id and
   differ only in their `observed_at`s, and the stored one is the first take's, which a
   later `twin create --snapshot <id>` records as the twin's. **The bundle's CTM sidecar `<bundle_id>.ctm.json` is retired**:
   no build writes one, and the ones on disk are never read. `bundles/.reads/` stays for
   the reconcile workflow alone, until following leaves.
3. **The server takes the snapshot.** For `twin create --branch` and `--stage`, the server
   reads, builds the snapshot, files it, compiles, files the bundle, and starts the
   provision workflow with the snapshot id and the bundle id, exactly as step and
   rehearse start theirs: the workflow begins at the host check with both ids and runs
   no read and no compile, and a refusal at read or compile is the server's document
   before any run, as step's is. The read is bounded by M1's read bound, as the server's
   reads for dry runs, step and rehearse already are; the activity's retries and
   heartbeat are given up for create, as they were for those, and the brief says so.
   **The reconcile workflow is untouched**: it reads the branch on its schedule through
   `ReadIntent` and the compile activity, which stay in the worker for it alone, reading
   `bundles/.reads/` as today, and it compares bundle ids as today. A twin its rebuild
   made therefore has no snapshot id, until following leaves.
4. **The snapshot as a direct input.** `twin create --snapshot <id|file>` and `twin
   compile --snapshot <file>` take one: an id is looked up
   in the store and refused when absent; a file is read by the client and sent, as `twin
   compile --ctm` sends a CTM today, refused when its `snapshot_id` does not match the
   id the server computes. Create files the snapshot under that id; `twin compile
   --snapshot <file>` compiles it and files nothing, as `--ctm` files nothing today and
   as the command needs no state root. **`--ctm` is retired**: the compile's one input is
   the core's, `intent read --out` writes what it takes, and a hand user wraps a bare CTM
   in the outer fields, so `snapshot_id` is optional in a file the client sends, computed
   by the server when absent and checked when present. `testdata/snapshot/` holds the
   three fixture CTMs wrapped, beside `testdata/ctm/`, for the README's offline example
   and any test that wants a snapshot file; tier 3's read-then-compile helper changes its
   flag. There is no fetch by id over the API, as there is
   none for a bundle; a dry run and a plan file their snapshot and bundle and print the
   store's paths. `intent read --out <file>` writes a snapshot, and files it,
   so a hand read and a create of the same intent share one stored document. `twin create
   --branch x` stays one step for the operator. **A `--snapshot` twin is frozen**: its
   reference is a document, which does not move, so `--interval` with `--snapshot` is
   refused before any connection by `follow.flags.conflict` in the rule's words, "a twin
   built from a snapshot never follows", `--no-follow` is accepted and redundant as with
   `--at`, and no Schedule is made whatever the envelope's `at` says. It has no stage, so
   it does not step until F-026. **`twin show` says it is of what its envelope says**:
   kind `pinned at T; not following` when the envelope carries an `at`, `frozen; not
   following` when it does not, by the existing rules, and the record line `record: branch
   B at T, snapshot <id>, bundle_id …` as every twin's; that it was asked for by snapshot
   is in the record's `source` and in the kind line's note, `built from snapshot <id>`.
   `from a bundle` stays the one kind for a twin with no envelope. **`twin step` keeps its one input,
   `--stage`**, and its guard that only a twin built from a stage steps: the server
   resolves the stage, takes its snapshot and starts the step workflow with the snapshot
   id and the bundle id, as it starts it with the bundle id today, so the core's step takes
   a snapshot while the operator's command does not yet. `--snapshot` on step arrives with
   following's removal, where a twin is frozen at its snapshot and the guard's reason goes.
5. **The rehearsal takes every stage's snapshot in its plan**, up front, as it already
   compiles every stage up front, so a refused stage is found before the first boot. The
   step-to-nowhere rule (`rehearsal.steps.none`) is unchanged: it judges as 015 defined
   it, by whether one stage alone compiled.
6. **The records**, by one rule: wherever a bundle id appears, the snapshot id sits beside
   it, except in the bundle.
   - `twin.json` `8` to `9`: the record names its snapshot id, and the step block's two
     sides each name one. A twin `twin provision <bundle-dir>` built has none, and so
     has one a following rebuild made while following exists; the record says so rather
     than inventing one, and `twin show` prints `snapshot none`.
   - `twin show`: the record line reads `record: <ref>, snapshot <id>, bundle_id <id>,
     …`; `show.schema.json`'s description gains its F-024 sentence as it did at each
     milestone.
   - the README's walk-through and `docs/architecture.md`'s command list, where
     `twin compile --ctm` is shown.
   - `stage plan`: each compiled stage names its snapshot id beside its bundle id.
     `stage list` does not, since it neither reads nor compiles.
   - the step record and the rehearsal's per-stage rows carry it; the report's table gains
     a `snapshot` column before `bundle`, in the same eight-character short form, inside
     the existing `CommentMax` guard.
7. **The contracts in prose.** `cli.md` gains its F-024 section: the one-step create kept,
   `--snapshot` on create, step and compile, `intent read` writing a snapshot, and the
   client's file rules for a snapshot file, and `--ctm` retired. `api.md` gains the additive arguments and
   answers under version `1`, pre-1.0 as at 014, 015 and 017.
8. **The decision entry**, one, D-061: the snapshot as the core's one input, with the
   wrap, the hash rule, the store and the retired sidecar in it; and Constitution VI's
   amendment, 2.1.0 to 2.2.0, citing it. The plan template's Constitution Check names
   2.2.0.
9. **The documents**: the glossary (snapshot, snapshot id, snapshot store; the bundle
   store's entry loses its sidecar sentence); `docs/architecture.md` §4.2 and §4.3 (the
   compiler's input is a snapshot's CTM), §4.4 (the provision workflow's steps), §4.5 (the
   state root's directories) and §4.6 (the commands); the C4 model redrawn for the new
   package and store, `make diagrams`; `docs/development.md` where it names the sidecar or
   `.reads/`; `CLAUDE.md`'s Formats and State; and the roadmap ([Owed](#exit)).
10. **Tier 3 gains no case.** Its nine cases run as they are; the greps over `twin show`'s
    record line move with the line, and case 5's read `snapshot none` after its rebuild.

<a id="decided"></a>
## Decided

Each settled with the operator on 2026-10-27.

- **Wrap, not absorb.** The snapshot is a thin document around an unchanged CTM 2, not a
  CTM 3 that gains the probe slot and loses `observed_at`. The CTM stays the reader's
  contract; the snapshot becomes the core's. The cost is one more noun and that `intent
  read --out` writes a snapshot.
- **The id hashes the body minus the inner `observed_at`**, by the manifest's precedent,
  and nothing else is kept out of it.
- **The server takes the snapshot; the one-step create is kept.** Two of the three live
  paths already read on the server; the third joins them. The core's workflows then take
  a snapshot alone and never see a branch.
- **Bundle 5 and the three goldens do not move.** The snapshot id is a property of the
  input and lives in every other record that names a bundle id.
- **Everywhere a bundle id appears**, the snapshot id sits beside it, except in the bundle.
- **The rebase limit is documented, not tested.**
- **Stored forever, beside the bundles, and the sidecar is retired.** The roadmap's
  "nothing need be kept" reads as a statement about Infrahub: a stage's snapshot can be
  taken again while the branch's history stands, so losing the store loses nothing that
  cannot be re-read.
- **The server compiles a create, and the workflow runs no compile.** The reader's
  check found the brief saying both; the step's and rehearse's path is the precedent, and
  the compile activity stays for reconcile alone. Settled by the brief's author, 2026-10-27.
- **The store never overwrites, `twin compile` never files, and a rebuilt following twin
  has no snapshot id until following leaves.** Each the bundle store's, the compile
  command's or the next spec's precedent, settled by the brief's author on the reader's
  check, 2026-10-27.
- **A `--snapshot` twin is frozen by rule**, whatever its envelope says, so the interval
  before F-026 has one rule and F-026 makes it universal. Following a branch the operator
  never typed, on a timer they never set, was the alternative. The operator chose this on
  2026-10-27.
- **A `--snapshot` twin is of what its envelope says.** A twin of the fixture pinned at T
  is the same twin however it was asked for, so no new kind beside `from a bundle` and no
  new line shape; the note names the snapshot. The operator chose this on 2026-10-27.
- **`twin compile --ctm` is retired.** The compile of a CTM is exactly the compile of its
  wrapped snapshot, so nothing is lost but a flag, and the one-input claim holds in the
  hand tool too. The operator chose this on 2026-10-27.
- **`twin step` stays stage to stage.** Relaxing `step.twin.unsteppable` so that any twin
  steps to any snapshot would give the step record a stage-less side, the checks that read
  a stage on both sides a rule for none, and a `--branch` twin its first step. The
  operator chose to keep the guard on 2026-10-27 and hand `--snapshot` on step to F-026.
- **The step-to-nowhere rule is unchanged.** It judges as 015 defined it, by whether one
  stage alone compiled, not by bundle equality as this brief first said. The snapshot
  column lets the reader see why two stages are the same; the rule's judgement is still
  right.
- **`probes` is reserved, empty and required, in version 1.** 016 fills it with a version
  bump and no change to how a snapshot is taken, stored or handed to a workflow.
- **Following leaves Fylgja's core in its own spec, straight after this one and before
  016**, not inside this feature, so that this feature's exit criteria say what the
  snapshot proved and nothing else ([Hand-off](#hand-off)).
- **Out of this feature**: the split itself and the orchestrator's platform; the API's
  shape for long operations (start, an operation id, poll), which the roadmap calls the
  orchestrator's first demand and which nothing here needs; probes (016); the NetBox reader
  (F-025); following's removal (the next spec); any change to the CTM, the compiler, the
  template, the schema on `main` or the fixtures.

<a id="open"></a>
## Open, for clarify

Nothing: the three questions this brief first left open (`--ctm` retired or kept, a
`--snapshot` twin and following, and what `twin show` says such a twin is of) were put to
the operator on 2026-10-27 and are under [Decided](#decided). Clarify may still find its
own.

<a id="left-to-the-plan"></a>
## Left to the plan

- **The id's algorithm**: the bundle's (SHA-256 over canonical bytes, 64 hex characters,
  eight shown), unless a reason to differ appears. The canonical encoding reuses
  `ctm.Normalize` and `ctm.Marshal` for the inner CTM.
- **The outer part's exact fields and names**, whether the take's `observed_at` is a copy
  of the inner CTM's or the two may differ (a snapshot file read later has only the
  inner one). `snapshot_id` is optional in a file the client sends;
  `snapshot.id.mismatch` means a declared id the body does not hash to, never a differing
  `observed_at`.
- **The record's `source`**: whether a `--snapshot` twin needs a third value beside
  `intent` and `bundle`, and the comment on `intent`, "read and compile ran in the run",
  which goes stale for every create once the server reads.
- **The store's interface and directory**, and whether the snapshot store and the bundle
  store share one Go interface or two of the same shape.
- **Where the two tier-2 cases live**: `internal/stage`'s
  `TestPinnedReadReproducesItsBundle` gains the id assertion; the stage-twice case sits
  beside it or in `internal/stages`.
- **The record formats that move and their frozen copies** under
  `testdata/contracts/`: `twin.json` `9`, `show`, `stages`, `step`, `rehearsal`.
- **`intent read`'s summary line** and how `--out` reports a snapshot it also filed.
- **The dry run's and create's answers**: where the snapshot id and the store's path go
  in the findings document's blocks.
- **D-061's text and VI's amendment text**, and the glossary entries.
- **The C4 redraw**: the server's components gain the snapshot package and store; the
  worker's provision loses its read.
- **No Infrahub skill applies**: this feature designs nothing in Infrahub, writes nothing
  to `main`, and changes no query, template or check.

<a id="hand-off"></a>
## Hand-off

- **To the next spec, following's removal** (a new backlog entry, F-026, placed straight
  after F-024 and before 016): D-012 in the part that says an unpinned twin follows its
  branch, D-026 and D-027 whole; the reconcile workflow, the Schedule `fylgja-follow`, its
  two activities, `ReadIntent` and `bundles/.reads/`; `--interval` and `--no-follow`;
  `twin show`'s kind line, where pinned, frozen or following collapses to the snapshot the
  twin was built from; `twin step --snapshot <id|file>`, with `step.twin.unsteppable`
  relaxed so that a twin steps to any snapshot, the step record's stage-less side and the
  checks' rule for it; tier 3's case 5 and the Schedule assertions in cases 5 and 7; the
  architecture, glossary, C4, CLI and API contracts; and the roadmap's bullet planning a
  push-based follow for F-025, struck from the decisions the order needs. The constitution
  does not mention following. Its entry says following leaves the core, not Fylgja: the
  production shape's orchestrator may bring it back as take, compare, rebuild. Its one
  exit criterion this feature lacks: a twin is frozen at its snapshot and nothing rebuilds
  it but the operator.
- **To 016**, whose brief predates snapshots and is re-read at its specify: the probe set
  is not a second input to the compile but part of the snapshot the reader takes;
  `twin compile` does not take it as a file, the snapshot carries it; it is hashed by the
  snapshot id and reaches the bundle through the synthesized nodes and the manifest; and
  `intent read` gains the way to put a declaration file into the snapshot, the declaration
  being a file first. **One question this feature leaves to 016**: it wants the probe set
  "read once and constant across a twin's life", and a rehearsal now takes one snapshot
  per stage, so either the orchestrator carries the first take's probe list into every
  later snapshot of that rehearsal, or each stage's take reads the probes afresh.
- **To F-025**: Constitution VI's new sentence, and a reader that produces snapshots and
  files them, where a stage is the snapshot Fylgja holds.

<a id="exit"></a>
## Exit

- **Tier 1**: two CTMs differing only in `observed_at` hash to one id; a reordered CTM
  hashes the same after normalising; a changed artifact byte or fidelity row moves it;
  the id equals a hash the test computes independently over the stored body minus the
  inner `observed_at`; a snapshot with a CTM that fails CTM 2's validation, or a wrong
  version, or a mismatched id, is refused by the rule named; the compile of a snapshot
  equals the compile of its CTM, so the three goldens stand unchanged; the five records
  carry the id and their frozen copies still load.
- **Tier 2**: the same intent read twice gives the same snapshot id, in the existing
  reproducibility test; the same stage resolved twice, through the server's path, gives
  the same id; `internal/stages` and `internal/checks` pass with the id in their rows.
- **Tier 3**: the nine cases pass as they are, `twin show`'s record line naming a snapshot
  id beside the bundle id; no case is added.
- **The live fixture** still compiles to `f764e1fa…`, and `CLAUDE.md` records the
  snapshot id it reads to.
- **Owed before the work starts**: the roadmap's F-024 paragraph reworded for the wrap
  and the retired sidecar, and F-026 added before 016 with the hand-off above (both done
  2026-10-27); the operator aware that nothing on Infrahub's `main`, no fixture and no
  golden moves.

<a id="references"></a>
## References

Read in this order, after `CLAUDE.md`'s list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Release 0.3](../../docs/roadmap.md#release-03), [The production shape](../../docs/roadmap.md#the-production-shape), [F-024](../../docs/roadmap.md#f-024), [F-025](../../docs/roadmap.md#f-025), [F-014](../../docs/roadmap.md#f-014), [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope, the seam this proves, and the two specs that consume it |
| [docs/decisions.md](../../docs/decisions.md): D-010, D-011, D-012, D-014, D-023, D-026, D-040, D-045, D-055, D-057, D-058, D-060 | what this feature builds on and leaves alone |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) 2.1.0: V, VI, IX, X | the Constitution Check, and the principle amended |
| [docs/verified-facts.md](../../docs/verified-facts.md): pinned reads, group joins, rebase | what the tier-2 proof rests on |
| [contracts/ctm.schema.json](../../contracts/ctm.schema.json), [manifest.schema.json](../../contracts/manifest.schema.json), [twin.schema.json](../../contracts/twin.schema.json), [show.schema.json](../../contracts/show.schema.json), [stages.schema.json](../../contracts/stages.schema.json), [step.schema.json](../../contracts/step.schema.json), [rehearsal.schema.json](../../contracts/rehearsal.schema.json), [cli.md](../../contracts/cli.md), [api.md](../../contracts/api.md) | the document wrapped, the one that must not move, and the five that do |
| [docs/architecture.md](../../docs/architecture.md) §4.2 to §4.6 | the CTM, the compiler, the provisioner, the state root and the commands |
| [docs/glossary.md](../../docs/glossary.md): Bundle, `bundle_id`, Bundle store, CTM | the entries the new ones sit beside |
| [internal/ctm](../../internal/ctm) (`types.go`, `json.go`), [internal/compiler/manifest.go](../../internal/compiler/manifest.go), [internal/bundle/store.go](../../internal/bundle/store.go), [internal/findings](../../internal/findings) | the encoding, the hash precedent, the store to mirror, the rules to mirror |
| [internal/server](../../internal/server) (`read.go`, `create.go`, `dryrun.go`, `filing.go`, `step.go`, `rehearse.go`, `compile.go`), [internal/stage/stage.go](../../internal/stage/stage.go), [internal/stages](../../internal/stages) | where the server already reads, compiles and files |
| [internal/provision](../../internal/provision) (`workflow_provision.go`, `workflow_step.go`, `activities.go`, `workflow_reconcile.go`, `types.go`) | the read that leaves the workflow, the one that stays, and the step guard that is kept |
| [internal/rehearsal/markdown.go](../../internal/rehearsal/markdown.go) | the report's table and its size guard |
| [internal/stage/reproducibility_contract_test.go](../../internal/stage/reproducibility_contract_test.go) | the tier-2 test the proof extends |
| [016's brief](../016-probes/brief.md) | the third spec, re-read against this one's close |
