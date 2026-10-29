# Specify brief: 0.3 spec 5 of 6: the split, the core and the orchestrator (F-027)

This is what `/speckit-specify` reads for roadmap F-027, the fifth spec of
[Release 0.3](../../docs/roadmap.md#release-03), six since the operator added F-027 on
2026-10-29 and placed it before F-025. It was **drafted on 2026-10-29 by a session**, from
the roadmap's [F-027](../../docs/roadmap.md#f-027) paragraph and
[production shape](../../docs/roadmap.md#the-production-shape), the decision log through
[D-064](../../docs/decisions.md#d-064), 016's close, the three earlier briefs' hand-offs
to the production shape and the NetBox spike's findings
([verified facts](../../docs/verified-facts.md#netbox-474-with-netbox-branching-122)),
for the operator to settle at feature-open: every entry under [Decided](#decided) marked
*proposed* is the author's and may be overturned there, and [Open](#open) holds the
questions only the operator can answer. **Fylgja becomes two deployables**: a core that
builds, steps, destroys, shows and verifies a twin from a snapshot and knows no branch,
proposed change, stage or source of truth; and an orchestrator that owns the readers, the
stages and their resolution, the rehearsal and the report posted back to the source, and
drives the core through the API alone. The session verified nothing live; the plan
verifies each point before relying on it. Constitution 2.3.0 binds the plan's check until
this feature amends it. Specify what the operator gets, not a new design.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/020-core-orchestrator-split GIT_BRANCH_NAME=020-core-orchestrator-split. 0.3, the fifth of its six specs: the split, the core and the orchestrator, as docs/roadmap.md's F-027 and Release 0.3 section define it. Read specs/020-core-orchestrator-split/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Why

- **The core still knows a branch.** Since 018 every workflow starts with a snapshot id
  and a bundle id ([D-061](../../docs/decisions.md#d-061)), since 019 none reads a source
  of truth ([D-062](../../docs/decisions.md#d-062)), and since 016 the one input that is
  not intent reaches the core inside the snapshot ([D-064](../../docs/decisions.md#d-064)).
  But the server still reads Infrahub for `twin create --branch` and `--stage`, `twin step
  --stage`, `intent read`, `stage list`, `stage plan`, `twin rehearse` and `schema check`,
  resolves stages, renders the rehearsal's report, and holds Infrahub's token; and
  `fylgja-rehearse` is the worker's fourth workflow
  ([D-051](../../docs/decisions.md#d-051)). The seam is proved on the core's side alone.
- **F-025 waits on the orchestrator's toolchain.** The NetBox reader is an adapter in
  Python, and built first it would invent the orchestrator's toolchain, flow shape, stage
  store and rehearsal ([F-025](../../docs/roadmap.md#f-025), settled 2026-10-29). The spike
  showed the core takes an adapter's snapshot unchanged, builds and steps from it, and that
  the snapshot id reproduces outside Go.
- **The production shape is a direction, and needs a decision.** The roadmap's
  [production shape](../../docs/roadmap.md#the-production-shape) says "nothing here binds
  a plan, and each part becomes a decision entry when a feature takes it up". This feature
  takes up its first sentence, the two components, and Constitution I is kept for the core
  and freed for the orchestrator by a decision entry, as the roadmap's
  [decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) owe at F-027.
- **The API's shape for long operations is the orchestrator's first demand.** A run is an
  open stream today, and "there is none to re-attach to a run, to list runs or to fetch a
  filed bundle" ([api.md](../../contracts/api.md)). A platform whose resume is a rerun must
  start a run, hold its id and poll it, or it starts a second run into `run.in_flight`.

## Where the shape is fixed

- **The roadmap's [F-027](../../docs/roadmap.md#f-027)**: its paragraph, its table row,
  [Release 0.3](../../docs/roadmap.md#release-03)'s item 5 and its bullet under
  [decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs); and
  the [production shape](../../docs/roadmap.md#the-production-shape), whose two components,
  Temporal kept in the core, Constitution I freed, platform lean (Prefect, with Temporal
  and Kestra beside it), long-operation shape and open product-or-contract question this
  brief takes up one by one. This brief departs from neither. The production shape's
  "explicit mutation of a node or a link" is not in F-027's paragraph and stays out
  ([Decided](#decided), Out of this feature).
- **F-025's shape, settled by the operator on 2026-10-29**: an adapter outside the core, in
  Python, built after this split as the orchestrator's second adapter, which takes the
  probe file alone; a stage there is the snapshot the adapter takes when the operator marks
  it, held by Fylgja. What this feature builds for Infrahub must leave that slot.
- **The hand-offs to the production shape** of [018](../018-snapshots/brief.md#hand-off)
  (the snapshot as the core's input, files it; a stage as a snapshot Fylgja holds),
  [019](../019-following-removed/brief.md#hand-off) (the core's surface is create, step,
  destroy, show and verify, with no timer; following returns outside it as take, compare,
  step) and [016](../016-probes/brief.md#hand-off) (the declaration is the first input no
  source owns; the orchestrator writes it and the API takes it as a file).
- **[D-040](../../docs/decisions.md#d-040), [D-041](../../docs/decisions.md#d-041),
  [D-042](../../docs/decisions.md#d-042)**: the API is the boundary of the core and a
  user-facing client reaches it by no other path, held by a test over imports; the server
  runs on the lab host and reads the host in its own process; one token from the
  environment. All three stand; the orchestrator is the API's next client.
  **[D-050](../../docs/decisions.md#d-050)**, the bridge listener: moved to the
  orchestrator's side ([Open](#open), question 5).
- **[D-051](../../docs/decisions.md#d-051)**, the rehearsal as a workflow: superseded here.
  **[D-052](../../docs/decisions.md#d-052)**, the check concludes from the report's status
  alone, Fylgja's verdicts advisory: stands. **[D-049](../../docs/decisions.md#d-049)** and
  **[D-053](../../docs/decisions.md#d-053)**, the check posts the report as a thread and
  Fylgja writes nothing: who posts is [Open](#open), question 4; the core writes nothing
  to Infrahub either way.
- **[D-057](../../docs/decisions.md#d-057), [D-061](../../docs/decisions.md#d-061),
  [D-062](../../docs/decisions.md#d-062), [D-064](../../docs/decisions.md#d-064)**: the
  CTM is the contract, the snapshot the core's one input, a twin frozen at it, a probe
  carried in it. None moves: CTM `2`, snapshot `2`, bundle `6` and the four goldens stand,
  and the fixture's snapshot id (`0940db93…`) and compiled id (`c3872f5c…`) are the test
  that the extraction changed nothing ([Exit](#exit)).
- **[D-005](../../docs/decisions.md#d-005)** and **[D-018](../../docs/decisions.md#d-018)**:
  Go end to end, one binary in three roles. From this feature they are the core's: D-005's
  own "honest counter-case" (adoption beats elegance where contributors write Python) is
  what the orchestrator takes up.
- **[D-001](../../docs/decisions.md#d-001)**: superseded in the part that says NetBox lacks
  branching, owed here by the roadmap since 2026-10-29. Infrahub stays the first source of
  truth and the one the development host runs.
- **[Constitution 2.3.0](../../.specify/memory/constitution.md)**: I (Go, end to end) is
  kept for the core and freed for the orchestrator; III (a reader maps one source) binds
  the readers, which become the orchestrator's adapters; VIII (Temporal) and IX (no
  database) stay the core's; VI (intent is addressed) and X (report honestly) bind both;
  XI (the API is the boundary) gains the orchestrator as a client, and its "no command of
  the CLI runs the core in its own process" holds for the core's CLI. The amendment is
  MAJOR by Governance's rule, since I is redefined in its scope; the text is the plan's
  ([Left to the plan](#left-to-the-plan)).

<a id="what-changes"></a>
## What changes, and nothing else

1. **The core's surface narrows to the snapshot.** The core is the `fylgja` binary in its
   three roles, unchanged in name.
   - **The API keeps** `twin.create` (`snapshot`, `dry_run`), `twin.provision`,
     `twin.step` (`snapshot`, `allow_restart`, `wait`, `dry_run`), `twin.destroy`,
     `twin.show`, `twin.verify`, `twin.compile` and `psp.validate`, each as
     [api.md](../../contracts/api.md) has it. **It loses** `twin.rehearse`, `stage.list`,
     `stage.plan`, `intent.read` and `schema.check`, and the arguments `branch`, `at`,
     `stage`, `scope` and `probes` wherever they are taken: `twin.create` and `twin.step`
     take `snapshot` alone, a filed id or a file sent, which carries its probes
     ([D-064](../../docs/decisions.md#d-064)). The CLI loses the same commands and flags.
   - **The server's environment** loses `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` and
     `FYLGJA_DEFAULT_SCOPE`; it dials the workflow service, Docker, containerlab and the
     nodes, and nothing else. Its start-up report says so. The worker's environment does
     not change.
   - **The identifiers that leave the core**: every `scope.*`, `stage.*`, `stages.*`,
     `rehearsal.*`, `schema.*` and `intent.*` rule the server made, each kept by the
     orchestrator or the adapter where its rule moved whole; `snapshot.flags.conflict`;
     and the step's stage-shaped targets. The step's rule that a twin never steps to
     another scope or mapping stays, read from the two snapshots' envelopes, which the
     core holds ([D-062](../../docs/decisions.md#d-062)).
   - **`twin.json` moves to `12`**: the stage a twin was built from, the stage a step
     brought it to and the rehearsal block go; the snapshot, the bundle, the scope and the
     mapping stay. `twin show`'s kinds (`none`, `snapshot`, `from_bundle`, `diverged`)
     stand; its stage line goes. A record of `11` or earlier is shown and destroyed, never
     stepped from, as 019 and 016 did with theirs.
2. **The worker serves three workflows.** `fylgja-rehearse` goes, with the rehearsal's
   reclaim, deadline and ceiling, which become the orchestrator's; D-051 is superseded.
   Provision, step and destroy stand under their fixed ids, and the seventeen activities
   stand. The 015 defect the release took with no spec, a client following a rehearsal
   terminated outside Fylgja that answers only once its abandoned children close
   (`specs/015-proposed-change-rehearsal/research.md` §5.2), goes with the parent workflow:
   the author's reading, which the plan confirms or corrects.
3. **The API's shape for long operations.** `twin.create`, `twin.provision`, `twin.step`
   and `twin.destroy` take an argument (the plan names it) under which the answer ends at
   the run's identity instead of following it; a new operation reads a run by its identity,
   answering its events so far and, once it has ended, its document, both built from the
   run's history so that the server still keeps nothing between two requests
   ([D-014](../../docs/decisions.md#d-014)); and the interrupt reaches a run by its identity
   as well as by its stream. The stream stays for the core's own CLI, which follows a run
   as it does today. Whether `1` moves is the plan's: 019 removed arguments without a move,
   pre-1.0, and this feature removes operations.
4. **A pure step between two snapshots, as an operation of the core.** The stage plan and
   the report's drawing need the step between each pair of stages, which `internal/stages`'
   plan computes today by compiling each stage and diffing the pair through
   `internal/step` ([plan.go](../../internal/stages/plan.go)). The adapter does not compile
   ([Decided](#decided)), so the core gains one operation that compiles two snapshots and
   answers the step between them (nodes and links changed, artifacts moved), pure, on the
   goldens' code path (Constitution V); its name is the plan's, and the orchestrator's plan
   and rehearsal flows are its consumers. *Proposed* by the author; the alternative is the
   plan showing snapshot and bundle ids alone, which loses the drawing's edges.
5. **The Infrahub adapter, a tool of the orchestrator, and a reader alone.** A second
   binary of the Go module, `cmd/fylgja-infrahub` (the name is the plan's), made from
   `internal/intent`, the reader's half of `internal/stages` (the reference, its resolution
   to `(branch, at)`, the staleness rule and the list), the read-and-take half of
   `internal/stage`, the probe reader and the schema check, with no code added to them that
   a move does not need; the plan's compile-and-diff half of `internal/stages` and the
   baseline rule (015 R-03) are not moved but re-made in the orchestrator over the core's
   operations (items 4 and 6), since the adapter never compiles. It reads a branch, a pinned
   branch or a stage, under a scope (`tag:<name>`, `FYLGJA_DEFAULT_SCOPE` its default now),
   with probes from a file, else `FylgjaProbe` on the default branch, else none, and writes
   a snapshot `2` file whose id is the one the server files today; it lists a proposed
   change's stages and what each resolves to; it checks a branch's schema against the
   mapping. It embeds the platform packages as the core does, with the same override
   directory, because the CTM names each device's package
   ([ctm.schema.json](../../contracts/ctm.schema.json), `platform.package`) and the read
   refuses a platform no package matches ([D-057](../../docs/decisions.md#d-057)); a skew
   between the two binaries' packages is refused by the core when it takes the snapshot,
   never silent. Its environment is `INFRAHUB_*` and the default scope; it holds no node
   login and never the API's token. The boundary is held by tests over imports both ways:
   `cmd/fylgja` links neither `internal/intent` nor `internal/stages`, and the adapter
   links neither `internal/provision`, `internal/lab` nor `internal/server`. Whether the
   adapter stays Go in this feature is [Open](#open), question 2.
6. **The orchestrator.** A Python project on Prefect ([Open](#open), question 1), under
   `orchestrator/` (the name is the plan's) in this repository ([Open](#open), question 6).
   - **Its flows**, each a Prefect flow and a deployment: a read (branch, pinned branch or
     stage, with probes) to a snapshot file, through the adapter; a create from a branch or
     a stage, which reads then calls the core's `twin.create`; a step to a stage, which
     reads then calls `twin.step`; the stage plan, which reads every stage, compiles each
     through `twin.compile` and asks the core for the step between each pair (item 4); the
     rehearsal, which plans, reclaims a twin its own dead run left, creates from the
     baseline, steps and verifies each later stage in order through the step's wait, stops
     at the first that fails, destroys whatever happened, computes each stage's verdict and
     the report, and posts it ([Open](#open), question 4); and the schema check, passed
     through. Each flow's refusals keep 014's and 015's identifiers and wording where the
     rule moved whole.
   - **Its CLI** ([Open](#open), question 3): one console script, noun-verb, whose
     commands are the ones the core's CLI loses, `intent read`, `stage list`, `stage plan`,
     `twin create --branch|--stage`, `twin step --stage`, `twin rehearse` (`--markdown`
     kept) and `schema check`, each running its flow and printing the same findings
     document the core's CLI printed, exiting by its status.
   - **Its state**: Prefect's own, in Prefect's server, as Temporal holds the core's run
     history; a directory of its own under its state root for every snapshot it takes, by
     id, the seed of the stage store F-025 fills for a source that cannot replay time; and
     one record of the twin it last drove, the stage it created or stepped it to, that
     stage's snapshot id and the flow run that did it, read beside the core's `twin show`
     and trusted only while the two name one snapshot. The record is what `stage list`'s
     twin row, `twin step`'s default target (the next stage of its own) and
     `stage.twin.moved` read now that `twin.json` names no stage, and what the reclaim
     reads to tell its own dead run's twin from the operator's. Files, no database of
     Fylgja's own.
   - **Its environment**: `INFRAHUB_*` and `FYLGJA_DEFAULT_SCOPE` for the adapter,
     `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` for the core, Prefect's own address;
     never a node login.
   - **Its documents**: the `rehearsal`, `stages` and `plan` blocks, their text and the
     markdown report as 014, 015 and 016 shaped them, so that the checks and the report's
     readers see no change but the author's name in the reproduce lines (Constitution XI's
     "the documents Fylgja already versions"); they move from the core's contracts to the
     orchestrator's. The text and markdown renderers are a port of what `internal/rehearsal`,
     `internal/findings`' text form and the server's list and plan printers render today,
     held to goldens captured from the Go implementation before it is removed (item 11).
   - **The rehearsal's deadline** is the flow's, derived from the stages' budgets as
     D-051 derived it; how the flow learns the packages' budgets without loading the
     packages is the plan's. A flow that times out or is cancelled still destroys.
7. **The checks are clients of the orchestrator.** `fylgja-step` and `fylgja-twin` stay
   Python glue under `infrahub/checks/`, run by Infrahub's task workers on every proposed
   change; each triggers its flow's deployment through the orchestrator's platform API on
   the host's Docker bridge, waits for the flow run, reads its document and concludes from
   the status alone (D-052). `fylgja_api.py` becomes that glue; the retry while the host is
   held (015 R-15) and the deadline margin move with it. `fylgja-twin`'s `timeout` of 4260
   stands until the plan measures the flow's overhead.
8. **The core's listener.** The server listens on loopback alone on the lab host, the
   orchestrator reaches it there, and the bridge listener and D-050 move to the
   orchestrator's platform API, which the Compose override's two variables point at
   ([Open](#open), question 5). `SECURITY.md`'s threat model follows.
9. **The decision entries**, two. **D-065**, the split: two deployables; the core's surface;
   the orchestrator's platform and language; the orchestrator drives the core through the
   API alone and never starts its workflows; Temporal stays in the core; the long-operation
   shape; Constitution I kept for the core and freed for the orchestrator; D-051 superseded,
   D-018 and D-040 read as the core's, D-050 moved, D-049 and D-053 in their "who posts" if
   question 4 says so. **D-066**, stages across sources: a stage resolves to a snapshot id;
   where the source replays time, by a pinned read at the mark (D-045); where it cannot,
   the snapshot the adapter took when the operator marked it, held by the orchestrator; and
   D-001 superseded in the part that says NetBox lacks branching. Constitution **3.0.0**.
10. **The repository and the toolchain.** `orchestrator/` with its `pyproject.toml`, its
    tests and its lint; `cmd/fylgja-infrahub`; CI's unit job runs the Python tests beside
    `go test`, and its lint job the Python linter beside golangci-lint and ShellCheck; the
    bring-up script gains a part that installs the orchestrator's venv and Prefect, starts
    its server and worker detached as the three processes are, and the development host
    runs five processes; `make` gains the orchestrator's targets. Which venv the
    orchestrator uses, beside the `.venv` that holds `infrahubctl`, is the plan's.
11. **The tiers.** Tier 1: the Go tests as today, less the moved packages' share, plus the
    boundary tests and the Python tests of the flows' pure parts (the verdict, the report,
    the deadline, the text and markdown renderings), against goldens captured from the Go
    implementation: a `stages`, a `plan` and a `rehearsal` document with their text and
    markdown, taken by a live run before the Go renderers go, so the route captures before
    it removes. Tier 2: the adapter's contract
    tests, which are `internal/intent`'s, `internal/stages`' and `internal/stage`'s today,
    unmoved but for their binary; the orchestrator's flows against the real Infrahub and a
    core server started with no Infrahub credential; `TestChecksInsideInfrahub` reaching the
    orchestrator's platform on the bridge, skipping where it reaches none, as it does for
    the server today. Tier 3: nine cases, every command that names a branch, a stage or a
    rehearsal through the orchestrator's CLI, case 9's two rehearsals through Infrahub's
    task workers, the orchestrator and the core; `E2E-OK` and the credential greps extended
    to the orchestrator's logs. Nothing of the core's tiers moves that the split does not
    move.
12. **The documents.**
    - **The contracts:** [api.md](../../contracts/api.md) (the operations lost, the
      long-operation shape, the step between two snapshots), [cli.md](../../contracts/cli.md)
      (the commands lost), a contract of the orchestrator's CLI and documents (the moved
      `rehearsal`, `stages` and `plan` blocks and the markdown), the checks' contract moved
      from [015's](../015-proposed-change-rehearsal/contracts/checks.md) to `contracts/`,
      where `.infrahub.yml` and both checks already cite it, `twin.schema.json` (`12`),
      `api.schema.json`, and the frozen copies the older tests read.
    - **[docs/architecture.md](../../docs/architecture.md):** §1 (a second deployable), §2
      (the pipeline's read as the orchestrator's), §4.1 (the reader as an adapter), §4.4
      (three workflows), §4.6 (two surfaces), a section for the orchestrator, §5 (the
      stack), §6; and the C4 model redrawn with the orchestrator, its platform, the
      adapter and the two checks' new reach, `make diagrams` run.
    - **[docs/glossary.md](../../docs/glossary.md):** Core, Orchestrator, Adapter, Tool,
      and Flow (orchestrator) beside the probe's Flow of 016, told apart as Check and Check
      (Infrahub) are; Client, Server, Rehearsal, Stage, Check (Infrahub) reworded.
    - **[docs/development.md](../../docs/development.md)** (the layout, the tiers, the
      make targets, the bring-up part, the conventions for Python), **`SECURITY.md`**,
      **[README.md](../../README.md)**'s walk-throughs, **`CLAUDE.md`**'s Workflow,
      Environment, Formats and State, **[docs/verified-facts.md](../../docs/verified-facts.md)**
      (Prefect's facts), **[docs/brief.md](../../docs/brief.md)**'s Scope, Pipeline and
      CLI, and the roadmap (F-027's row with its description and estimate, the production
      shape's "a direction, not a decision" line, F-025's dependency; [Exit](#exit)).
    - **`.infrahub.yml`** unchanged but for the checks' bodies; the template and its
      query untouched.

<a id="decided"></a>
## Decided

Each was settled by the operator on 2026-10-25 (the production shape, discussed and
tabled) or on 2026-10-29 (F-027 added before F-025, with F-025's shape), unless marked
*proposed*, which is the brief's author on 2026-10-29, for the operator at feature-open.

- **Two deployables: a core and an orchestrator** (2026-10-25). The core builds, steps,
  destroys, shows and verifies a twin from a snapshot and exposes it through the API;
  nothing in it knows a branch, a proposed change, a stage or a source of truth. The
  orchestrator owns everything else and drives the core through the API alone, never by
  starting its workflows, so either side can be replaced.
- **Temporal stays in the core** (2026-10-25), where mid-flight durability matters, and is
  not the orchestrator's integration surface.
- **Constitution I is kept for the core and freed for the orchestrator** (2026-10-25), by a
  decision entry: the orchestrator calls tools written in anything.
- **The API gains a shape for long operations** (2026-10-25): start, an operation id, then
  poll, beside the stream the core's own clients hold open. A callback is not built
  (*proposed*: a later feature's, once a consumer exists, on D-040's rule against an
  endpoint with no consumer).
- **F-025 is built after this split, as the orchestrator's second adapter, in Python**
  (2026-10-29), so this feature decides the toolchain, the flow shape, the stage store's
  seed and the rehearsal it inherits.
- **D-001 is superseded in the part that says NetBox lacks branching, and a stage where
  the source cannot replay time is the snapshot Fylgja holds** (2026-10-29, the roadmap's
  bullet moved here from F-025).
- **The Infrahub adapter stays Go in this feature, extracted as a tool** (*proposed*;
  [Open](#open), question 2). The reader, the stage resolution and the schema check are
  about 20,000 lines with their tests, carry seven decision entries of verified Infrahub
  behaviour ([D-045](../../docs/decisions.md#d-045) to [D-048](../../docs/decisions.md#d-048),
  [D-058](../../docs/decisions.md#d-058) to [D-060](../../docs/decisions.md#d-060)) and
  most of tier 2's 34 minutes; moving them across a language line is a rewrite and a
  re-verification, not a split, and the production shape allows a tool in any language.
  *Not chosen now*: the rewrite in Python with `infrahub-sdk`, one toolchain for the
  orchestrator, which a later feature may take up once the flow shape is proved.
- **The orchestrator ships a noun-verb CLI of its own that prints the documents the core's
  CLI loses** (*proposed*; [Open](#open), question 3). CLI first
  ([D-019](../../docs/decisions.md#d-019)) and the findings document as the oracle of
  every tier hold on both sides. *Not chosen*: the core's `fylgja` CLI as a client of two
  servers, which ties the core's binary to the orchestrator's platform API.
- **The rehearsal's report is posted by the rehearse flow, and the check triggers, waits
  and concludes** (*proposed*; [Open](#open), question 4). Posting back to the source is
  the orchestrator's in the production shape, F-025's journal entry on a NetBox branch
  has no check to post it, and one flow then posts to either source. D-049 and D-053 are
  superseded in "the check posts" and kept in "a thread, as the view shows one". *Not
  chosen*: the check posting what the flow returns, as today, which leaves F-025 to invent
  a second posting path.
- **The core's server listens on loopback alone, and the bridge listener moves to the
  orchestrator's platform API** (*proposed*; [Open](#open), question 5). The task workers
  then hold the orchestrator's credential and never the core's token, which no longer
  crosses the bridge unencrypted. *Not chosen*: both on the bridge, which keeps a listener
  nobody dials.
- **The orchestrator lives in this repository** (*proposed*; [Open](#open), question 6),
  under one directory with its own toolchain: one history, one feature chain, the contracts
  and the frozen copies shared, CI's three jobs extended rather than doubled. *Not
  chosen*: a second repository, which the converge loop cannot run and which splits every
  feature's route in two.
- **The orchestrator holds the documents' shapes, not the core** (*proposed*): the
  `rehearsal`, `stages` and `plan` blocks and the markdown move to the orchestrator's
  contract unchanged, so a check or a reader of the thread sees the same report.
- **The adapter is a reader and never compiles; a pure step between two snapshots is the
  core's operation** (*proposed*; items 4 and 5 of [What changes](#what-changes)).
  [D-040](../../docs/decisions.md#d-040) rejected a compiler in a client, since a bundle
  compiled outside the server need not be the one the server compiles, and the adapter is
  a client's tool; the step is a pure function of two bundles
  ([internal/step](../../internal/step), held pure by a test), so the core answers it.
  *Not chosen*: `internal/stages` moved whole, compiler and all, which keeps its plan
  tests unmoved at the price of a second compile path outside the core.
- **The orchestrator keeps one record of the twin it drove** (*proposed*; item 6): the
  stage, its snapshot id and the flow run, as files beside its snapshots, trusted only
  while the core's `twin show` names the same snapshot. Without it `twin step`'s default
  target, `stage list`'s twin row, `stage.twin.moved` and the reclaim have nothing to
  read once `twin.json` names no stage. *Not chosen*: those four retired, so that every
  step names its target and a dead rehearsal's twin is the operator's to destroy; and a
  stage kept in the core's record, which is the knowledge the split removes.
- **Two decision entries, D-065 and D-066, and Constitution 3.0.0** (*proposed*): the
  split in one entry on D-061's pattern; stages across sources, with D-001's supersession,
  in a second, since F-025 will cite it alone.
- **The estimate is 16–24 hours of sessions** (*proposed*, the plan re-estimates):
  the core's narrowing, the long-operation shape, the record and the boundary tests 4–6;
  the adapter's extraction 2–3; the orchestrator, its flows, CLI, the documents'
  renderers, the checks' glue and the platform 7–10; the tiers, the bring-up part and
  the documents 3–5. 017, the largest
  feature so far, ran T001–T121 against 6–10.
- **Out of this feature:**
  - the explicit mutation of a node or a link, the production shape's sixth core operation;
  - following brought back by the orchestrator as take, compare, step, and a webhook or
    an event rule that starts it ([ideas](../../docs/ideas.md));
  - the NetBox adapter and its stage store (F-025), the Python rewrite of the Infrahub
    adapter, and a second orchestrator platform;
  - a callback on the core's API, a list of runs, or a fetch of a filed bundle or snapshot;
  - a gate that pauses a flow for a human, an automation fired by Infrahub's webhook,
    and any Prefect feature the open-source server lacks;
  - the remote hosts' runtime, the WebUI and the agent surface, each a later client;
  - any change to the CTM, the snapshot, the bundle, the probe declaration, the mapping,
    the schema library's files, the template or the step's and verify's rules.

<a id="open"></a>
## Open, for clarify

Each is the operator's, put at feature-open and moved into [Decided](#decided); `none`
before the chain starts.

1. **The orchestrator's platform.** *Prefect* (the roadmap's lead and the author's
   recommendation: the ecosystem's language, Infrahub's own checks run on it, flows as
   code, Apache 2, no Kubernetes, with the open-source server's boundary verified at plan),
   *Temporal in Go* (already in the stack, the most durable, the cheapest split: the
   orchestrator a second Go service driving the core through the API, which defers the
   platform question and makes F-025 a Python tool a Go orchestrator calls) or *Kestra*
   (declarative YAML, if the orchestrator is a contract others' flows fill).
2. **The Infrahub adapter in this feature.** *Go, extracted as a tool* (recommended, above),
   or *rewritten in Python with `infrahub-sdk`* (one toolchain; seven decision entries'
   verified behaviour and most of tier 2 re-proved in Python; about 017's size again on
   top of the split).
3. **The orchestrator's operator surface, and its name.** *A noun-verb CLI of its own that
   runs a flow and prints the document* (recommended), *Prefect's CLI and UI alone*
   (nothing to build, but the tiers lose their document oracle and the README its
   walk-through), or *the core's `fylgja` CLI kept as a client of both servers* (one
   command for the operator; the core's binary learns the platform's API). With the first,
   its name: two binaries on one `PATH` cannot both be `fylgja`, and the report's reproduce
   lines (`fylgja twin create --stage …`, contract text the README and tier 3 read) name
   whichever is chosen. The author recommends `fylgja-orchestrator`, on `fylgja-fixture`'s
   pattern.
4. **Who posts the report.** *The rehearse flow* (recommended) or *the check, as today*.
5. **The core's listeners.** *Loopback alone, the bridge the orchestrator's* (recommended)
   or *both kept on the bridge*.
6. **The repository.** *This one, under one directory* (recommended) or *a second*.

<a id="left-to-the-plan"></a>
## Left to the plan

- **Prefect, verified on the development host before the design**: the open-source
  server's boundary (events, automations, auth, result persistence, flow timeouts and what
  a cancelled or timed-out flow runs last, an ephemeral mode for the tiers); the version
  to pin; whether Infrahub 1.11.2's embedded Prefect is a separate server to run beside,
  as the roadmap assumes (`docs/verified-facts.md` names its `git_repositories_sync` flow);
  how a task worker's Python, holding `infrahub-sdk` alone, triggers a deployment and
  waits for its run over plain HTTP on the bridge; and whether a flow reaching the core's
  API on loopback at the core's token needs anything the host does not have. Each into
  `research.md` and, once it holds, [verified-facts.md](../../docs/verified-facts.md).
- **The core's new operations**: the argument that ends an answer at the run's identity,
  the read of a run by identity and its frames, the interrupt by identity, the pure step
  between two snapshots, and whether `1` moves.
- **The adapter's name, command shape and output**: the snapshot file's path, the stage
  list as a document, the schema check; its start-up line; how `twin create --dry-run` of
  the orchestrator's CLI reaches the core's dry run.
- **`twin.json` `12`**, and how `twin show` and the step's rule read the scope and the
  mapping from the envelopes.
- **The orchestrator's record of the twin** (item 6): its shape, where it lives, and how
  the reclaim reads it with Prefect's run state to tell a twin its own dead run left from
  the operator's.
- **The goldens' capture**: which live run takes the `stages`, `plan` and `rehearsal`
  documents with their text and markdown from the Go implementation (tier 3's case 9 and
  a hand rehearsal produce them; `local/` holds earlier runs' outputs), and where the route
  places that capture before the Go renderers are removed.
- **Whether the adapter links the compiler through `internal/validate`**, whose probe
  placement runs the compiler's, and if so how the test that it never compiles a bundle is
  written.
- **The rehearsal's deadline** from the stages' budgets without loading the packages,
  and `fylgja-twin`'s `timeout` against the flow's overhead.
- **The orchestrator's layout, venv, linter and test runner**, CI's two jobs extended, the
  bring-up script's part, the `make` targets, and whether `scripts/e2e.sh` starts an
  orchestrator of its own for the eight cases that need one, as it starts a core server.
- **Tier 2's new shape**: which contract tests move whole with their packages, which are
  written against the orchestrator, and the tier's wall time, with `internal/stages` at
  1,713 s against its 30-minute bound.
- **The Constitution Check**: the amendment's text per principle, the Development
  Workflow's "single Go module, one binary" as the core's, and 3.0.0's Sync Impact Report.
- **Which Infrahub skill to load**: none designs a kind; `infrahub-managing-checks` before
  `fylgja_step.py` and `fylgja_twin.py` are touched, as `CLAUDE.md`'s hook rule says.
- **The estimate**, re-made from the route, and whether the plan proposes a cut into two
  specs if its route runs past 017's.

<a id="operator-steps"></a>
## Operator steps

- [x] 016 merged into `main` and pushed: `origin/main` is `195af3a`, the merge. Done
  2026-10-29.
- [ ] Push `main` to `origin` before the chain (`git push origin main`): the roadmap's
  commit (`95c0246`) and this brief, once committed. A push during the chain would stop
  the loop at `contract`.
- [ ] `make command-log` for 016, once that session is closed.

Waiting for the chain, each the route's `[operator]` task with its reason:

- **Push the checks and import them**, since the import waits on the pushed tree: once
  `fylgja_step.py`, `fylgja_twin.py` and `fylgja_api.py` are the orchestrator's clients,
  merge into `main`, push `origin`'s `main`, then
  `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on `main` for the registration
  `fylgja`, and read both task workers' `commits/` (`CLAUDE.md`, Environment), as 016's
  T041 did. Before tier 2's `TestChecksInsideInfrahub` and tier 3's case 9.
- **Recreate Infrahub's task workers with the changed override**, since the override's
  two variables then point at the orchestrator: `docker compose -p fylgja-infrahub
  --env-file local/.env -f local/infrahub/docker-compose.yml -f
  local/infrahub/docker-compose.override.yml up -d` from the repository root, with no twin
  up and no tier running. The operator decides at feature-open whether a live run may do
  this instead; it needs no sudo.
- **The review, the merge and the push**, because they are the operator's at every
  feature's close, with `make command-log` once the session is closed.

<a id="hand-off"></a>
## Hand-off

- **To F-025**: the adapter's contract, a tool that reads one source under a scope and
  writes a snapshot `2` file with its probes from a file; the flows that take any adapter's
  file; the package match, since an adapter writes each device's package, so the Python
  adapter needs the packages' `platform.matches`, from the shipped YAML or from an
  operation of the core that F-025 asks for; the orchestrator's snapshot directory as the
  stage store's seed, and D-066's rule for a stage where the source cannot replay time;
  the report posted by the flow, which for NetBox is a journal entry on the branch. The spike's adapter under
  `local/netbox-spike/` is its first draft, not in the tree.
- **To the production shape**: following returns as a flow, take, compare, step, on a
  timer or on Infrahub's webhook ([ideas](../../docs/ideas.md)); the explicit mutation of
  a node or a link is the core's next operation; whether the orchestrator is a product or a
  contract stays open, with the platform chosen leaning to the first.
- **To F-012, F-013 and F-021**: each a client, of the core, of the orchestrator or of
  both; the agent surface's skill reads two CLIs' JSON.
- **To the release's close**: the production shape's "a direction, not a decision" line
  becomes a record of what was decided here, and 0.3's upgrade list gains the five
  processes and the checks' new reach.

<a id="exit"></a>
## Exit

**The one criterion:** a proposed change is rehearsed on a twin and its report posted,
by an orchestrator that reaches the core through the API alone, while the core's server
and worker hold no Infrahub credential and know no branch.

- **Tier 1:**
  - The boundary tests: `cmd/fylgja` links neither `internal/intent` nor
    `internal/stages`; the adapter links none of `internal/provision`, `internal/lab` and
    `internal/server`; `TestClientReachesTheCoreThroughTheAPIAlone` still holds.
  - The API's lost operations are `404` as "no operation at this path"; the lost arguments
    are refused as unknown; a run started detached ends at its identity, and the read of
    a run replays its events and document from a recorded history, the seven replay
    histories among them.
  - The worker registers three workflows; `twin.json` `12` round-trips; an `11` is shown
    and refused a step.
  - The pure step between two snapshots on the goldens: three-node to three-node-probed
    names the two hosts and their links.
  - The orchestrator's pure parts: each stage's verdict, and the `stages`, `plan` and
    `rehearsal` documents' text and markdown against the goldens captured from the Go
    implementation, byte for byte.
  - The goldens unmoved; `make test` inside its 65 s budget, the Python tests beside it.
- **Tier 2:**
  - The adapter's read of `fylgja-fixture` files the snapshot `0940db93…`, and its stage
    list and schema check answer what the server's did, each contract test green under its
    new binary.
  - The orchestrator's flows against the real Infrahub and a core server started with no
    `INFRAHUB_*`: a create from the fixture, a stage plan of a throwaway proposed change,
    a rehearsal refused before any run on a stale mark, and the composition
    `TestRehearseComposedByTheFixtureTool` exercises.
  - `TestChecksInsideInfrahub` green through the orchestrator's platform on the bridge, and
    skipping, saying why, where the task workers reach none.
- **Tier 3:**
  - Nine cases, `E2E-OK`: cases 1 to 8 through the orchestrator's CLI for every command
    that names a branch or a stage, case 3's dry run among them, and through the core's for
    the rest; case 9's two rehearsals asked by `fylgja-twin` from inside Infrahub, through the
    orchestrator, with the thread's table carrying the `loss` column as it does today.
  - The credential greps over the orchestrator's logs and Prefect's find nothing; the
    core's server log shows no request to Infrahub, since it can make none.
- **The goldens and the fixture's ids do not move**: bundle `6`, CTM `2`, snapshot `2`,
  `c70589c3…`, `10099944…`, `44ac283f…`, `5222063b…`, `0940db93…` and `c3872f5c…`.
- **Owed before the work starts:**
  - 016 closed, merged and pushed (done, 2026-10-29); this brief re-read against its
    [Hand-off](../016-probes/brief.md#hand-off) (done, the same day).
  - The roadmap reconciled: F-027's table row gains the description, the dependency on
    F-014 and the estimate [Decided](#decided) gives, and Release 0.3's item 5 links here;
    the production shape's "a direction, not a decision" is the close's, by the pattern
    016 set for F-014's paragraph.
  - The [Open](#open) questions settled at feature-open and this brief committed.

<a id="references"></a>
## References

Read in this order, after `CLAUDE.md`'s list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md), F-027, F-025, the production shape, Release 0.3 and the decisions the order needs | the feature's definition, the lean on each open point, and what is owed here |
| [D-040](../../docs/decisions.md#d-040), [D-041](../../docs/decisions.md#d-041), [D-042](../../docs/decisions.md#d-042), [D-050](../../docs/decisions.md#d-050) | the API as the boundary, the server on the lab host, the token, the bridge listener |
| [D-051](../../docs/decisions.md#d-051), [D-052](../../docs/decisions.md#d-052), [D-053](../../docs/decisions.md#d-053), [D-049](../../docs/decisions.md#d-049) | the rehearsal as a workflow, the check's conclusion, the thread |
| [D-061](../../docs/decisions.md#d-061), [D-062](../../docs/decisions.md#d-062), [D-064](../../docs/decisions.md#d-064) | the snapshot, the frozen twin, the probe in the snapshot |
| [D-005](../../docs/decisions.md#d-005), [D-018](../../docs/decisions.md#d-018), [D-001](../../docs/decisions.md#d-001) | Go end to end and its counter-case, one binary, Infrahub chosen and NetBox's premise |
| [D-045](../../docs/decisions.md#d-045) to [D-048](../../docs/decisions.md#d-048), [D-058](../../docs/decisions.md#d-058) to [D-060](../../docs/decisions.md#d-060) | what the adapter carries: stages, staleness, events, the stamps Infrahub's own account writes |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) (2.3.0) | I, III, VI, VIII, IX, X and XI, and the Development Workflow's repository gate |
| [contracts/api.md](../../contracts/api.md), [contracts/cli.md](../../contracts/cli.md), [contracts/api.schema.json](../../contracts/api.schema.json) | the operations and arguments that leave, the stream a long operation gains a sibling of |
| [contracts/rehearsal.schema.json](../../contracts/rehearsal.schema.json), [contracts/stages.schema.json](../../contracts/stages.schema.json), [contracts/twin.schema.json](../../contracts/twin.schema.json) | the documents that move to the orchestrator, and the record that loses its stage |
| [specs/015-proposed-change-rehearsal/research.md](../015-proposed-change-rehearsal/research.md) | how Infrahub runs a check (§1.2), what a timed-out one leaves (§1.4), the plan's R-01 to R-21 the flow re-makes, §5.2's defect |
| [specs/014-proposed-change-stages/](../014-proposed-change-stages/) | the stage surface's spec and contracts, which the orchestrator keeps |
| [specs/018-snapshots/brief.md](../018-snapshots/brief.md), [specs/019-following-removed/brief.md](../019-following-removed/brief.md), [specs/016-probes/brief.md](../016-probes/brief.md) | the hand-offs this feature inherits |
| [docs/verified-facts.md](../../docs/verified-facts.md), "NetBox 4.7.4 with netbox-branching 1.2.2" and Infrahub's check facts | what an adapter outside Go already proved, and what a check inside Infrahub can do |
| [docs/ideas.md](../../docs/ideas.md), "A webhook that starts a take and a step" | what the orchestrator may bring back later |
| [internal/server](../../internal/server), [internal/stage](../../internal/stage), [internal/stages](../../internal/stages), [internal/intent](../../internal/intent), [internal/rehearsal](../../internal/rehearsal) | what leaves the core: the handlers that read Infrahub, the read-and-take, the stages, the reader, the rehearsal's rules |
| [internal/provision](../../internal/provision), [internal/lab](../../internal/lab), [internal/step](../../internal/step), [internal/api](../../internal/api), [internal/cli](../../internal/cli) | what stays: the three workflows, the host, the pure step, the wire, the client |
| [infrahub/checks/](../../infrahub/checks/), [.infrahub.yml](../../.infrahub.yml) | the two checks and their glue, which become the orchestrator's clients |
| [scripts/e2e.sh](../../scripts/e2e.sh), [scripts/bring-up.sh](../../scripts/bring-up.sh), [scripts/infrahub/docker-compose.override.yml](../../scripts/infrahub/docker-compose.override.yml) | tier 3's cases, the host's parts, the task workers' reach |
| [docs/c4/workspace.dsl](../../docs/c4/workspace.dsl) | the model to redraw |
| [docs/templates/decision-template.md](../../docs/templates/decision-template.md) | the two entries' section list |
