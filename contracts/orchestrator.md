# Contract: the orchestrator — `fylgja-cli`, its documents, the adapter, the flows on their platform and the record (020)

Fylgja is two deployables ([D-065](../docs/decisions.md#d-065)): the core, which runs a twin
from a snapshot ([api.md](api.md), [cli.md](cli.md)), and the orchestrator, which owns the
source of truth, the stages and the rehearsal and drives the core through its API alone.
This file is the orchestrator's contract. The checks that reach it from Infrahub are
[checks.md](checks.md)'s.

The orchestrator took over from the core's CLI the seven commands that named a branch, a
stage or a rehearsal, with their documents and their refusals. **What a command prints,
its document and its exit are those `fylgja` gave for it**, as [cli.md](cli.md)'s sections
"014: the stage surface", "015: the rehearsal", "017: the scope and the DCIM reader",
"018: snapshots" and "016: probes" describe them, read with `fylgja-cli` for `fylgja`, but
for what this file names. Identifiers, exit statuses and the JSON documents are the
contract; text is illustrative except where a sentence is quoted.

## `fylgja-cli`

```text
fylgja-cli intent read   --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] --out <f>
fylgja-cli stage list    [--branch <b>] [--scope tag:<n>]
fylgja-cli stage plan    --branch <b> [--scope tag:<n>] [--probes <f>]
fylgja-cli twin create   --branch <b>|--stage <b>/<l> [--scope tag:<n>] [--probes <f>] [--dry-run]
fylgja-cli twin step     [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] [--allow-restart] [--wait <d>] [--dry-run]
fylgja-cli twin rehearse --branch <b> [--scope tag:<n>] [--probes <f>] [--markdown]
fylgja-cli schema check  --branch <b>
```

`--json` on the root and on every command; `--version`; `--help`. Installed by `make
orchestrator-venv` as `orchestrator/.venv/bin/fylgja-cli`, beside `fylgja-orchestrator`
(the runner, below).

| Command | Operation of its document | Flow | What it asks the core |
|---|---|---|---|
| `intent read` | `intent.read` | `intent-read` | nothing |
| `stage list` | `stage.list` | none: a plain body, recorded nowhere | `twin.show`, when the record names a twin |
| `stage plan` | `stage.plan` | `stage-plan` | `twin.compile` for each stage, `twin.diff` for each pair |
| `twin create` | `twin.create` | `twin-create` | `twin.create` with the snapshot's file, detached, then `run.read`; its dry run undetached; then `twin.show` |
| `twin step` | `twin.step` | `twin-step` | `twin.show`; `twin.step` with the target's file, detached, then `run.read`; its dry run undetached; then `twin.show` |
| `twin rehearse` | `twin.rehearse` | `twin-rehearse` | the plan's; `twin.show`; the baseline's dry run; `twin.create`, `twin.verify --wait`, `twin.step --allow-restart` and `twin.destroy`, each run detached then read; `run.interrupt` at the deadline |
| `schema check` | `schema.check` | `schema-check` | nothing |

- **Each command runs its flow in its own process.** With `PREFECT_API_URL` set, the flow
  runs on that platform and is recorded there, once `GET /version` has answered
  `PREFECT_API_AUTH_STRING`'s credential; one that does not answer, or answers otherwise,
  is `platform.unreachable` before any flow, exit 2. Unset, the flow runs on Prefect's
  ephemeral server under `PREFECT_HOME`, which needs no runner. `stage list` asks no
  platform. Before Prefect is imported the command gives two of its settings a default,
  each kept when the environment sets it: `PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL=CRITICAL`
  (the run's log repeats every out line) and
  `PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS=180` (a first start in a fresh home
  outlasts Prefect's 20 s; 020's research §5.17).
- **What it prints** is what `fylgja` printed: the out lines on stdout as they arrive, then
  the document's findings as text on stderr; under `--json` the document alone on stdout
  and no out line; under `twin rehearse --markdown` the report as markdown on stdout and
  nothing else there, the out lines and the findings on stderr. **It exits by the
  document's status**: `ok`, `rejected`, `error`, `failed`, `unclean`, `diverged` and
  `nonconforming` give 0, 1, 2, 3, 4, 4 and 5.
- **Its own refusals.** A flag the command does not know is the command's own document,
  `operation.failed`, exit 2, its JSON under `--json`; an unknown noun or verb is a line on
  stderr, `fylgja-cli: …`, exit 2, with no document; a noun alone, or nothing, prints its
  help, exit 0. `--markdown` beside `--json` is `operation.failed`, exit 2: `--markdown and
  --json cannot be given together: each is the one thing printed on stdout`. A flow that
  ends with no document (Prefect's own failure, an ephemeral server that does not start, an
  interrupt) is `operation.failed`, exit 2: `the flow <flow> did not end with its document:
  <why>; any run of the core's it started goes on, and fylgja twin show names it`.
- **An interrupt** ends the command, never the core's run: every run is started detached
  (below), so the first interrupt `fylgja` gave a followed run has no counterpart here.
  `fylgja run read` and `fylgja run interrupt` reach the run by its identity
  ([cli.md](cli.md), "020: runs by identity and the diff").

### What moved from `fylgja`'s commands

Each is a departure from the text and documents [cli.md](cli.md) gives, where the core's
words named what the core no longer does (020's research §5.13, §5.17, §5.19):

- **The scope.** `--scope` left out reads `FYLGJA_DEFAULT_SCOPE` where the command runs.
  `scope.unset` reads `no --scope was given and there is no default: name one with --scope
  tag:<name>, or set FYLGJA_DEFAULT_SCOPE where the adapter runs`; a default that is not
  `tag:<name>` is `scope.invalid` naming the variable's value, where the server refused to
  start. `twin step` takes `--scope`, left out the scope `twin show`'s record names, as the
  server read it, and the default when no twin is recorded.
- **The snapshot and its store.** A snapshot the orchestrator takes is filed under its own
  store (below) and sent to the core as that entry's file, under the entry's path, which
  the core files in its own; the document's subject is the command's (`branch`, `at`,
  `stage`, `scope`), with the core's run id once there is one. `intent read`'s summary line
  ends `; snapshot <id>, stored at <entry>` and names no lossy mappings or shared ports,
  which are the compiler's survey; the plan's `read` counts take them from each compiled
  manifest, 0 and 0 for a stage the core refused to compile.
- **The create and the step.** Their documents are composed from the core's answers: the
  command's findings first (the resolution's and the read's, `step.stage.skipped`,
  `stage.twin.moved`), then the start's but its `run.detached`, then the run's without the
  start's repeats; the start's blocks, the run's over them, the `stage` block over both.
  The create's dry run prints no `read:` line; the step's stage line prints before the
  core's `twin:` line. `twin step`'s `--wait` is the core's to refuse
  (`verify.wait.invalid` at `start`), after the target's read. `twin create` takes no
  `--at`. A stage whose build cannot run names its reference.
- **The step's default target** is the next stage of the proposed change the
  orchestrator's record names, read only while the record is trusted (below); a step given
  no `--stage` under a record not trusted is `step.target.required`, nothing read.
- **`stage list`** reads the record, and asks `twin show` only when there is one, after the
  guards; trusted, the record's stage marks its row; not trusted, `record.twin.stale` is the
  document's first finding and no row is marked. A record naming a mark since deleted shows
  no at's source.
- **The reproduce lines** of the rehearsal's report name `fylgja-cli twin create --stage …
  --scope …`, `fylgja-cli twin step --stage … --allow-restart`, `fylgja-cli twin verify`
  and `fylgja-cli twin destroy`.
- **The report's post** is the rehearse flow's, not a check's ("The rehearse flow", below).

### Identifiers

Every rule the core's server filed for a source of truth, a stage or a rehearsal left the
core at 020 and is the orchestrator's, with its identifier, severity, exit, step and
wording as [cli.md](cli.md) gives them: `scope.invalid`, `scope.unset`, `scope.empty`, every
`schema.*`, `stage.*` (but M2's `stage.failed`, the core's), `rehearsal.*` and `probes.*`
rule, `intent.at.precision`, `probe.kind.absent`, `snapshot.flags.conflict`,
`step.target.current` and `step.stage.skipped`. The adapter also files the core's own
rules where it refuses what the core would have refused alike (the read's `artifact.*`,
`platform.*`, `omit.*`, a CTM's intrinsic rules, a probe declaration's, a snapshot's).
`orchestrator/src/fylgja_orchestrator/documents/rules.py` holds every one as data; the
core's `TestTheOrchestratorsRulesAreRetired` holds each retired id absent from the core and
present there. Four are the orchestrator's own, and no core build ever filed them:

| Rule | Severity, exit, step | Object | When |
|---|---|---|---|
| `record.twin.stale` | info, 0, none | the record's path | `stage list` with a record not trusted: `the orchestrator's record names snapshot <id> from stage <branch>/<label>, and twin show's record names <snapshot <id>, or no snapshot, since no twin is recorded>; the record is not trusted, so no stage is marked as the twin's` |
| `step.target.required` | rejection, 1, `start` | `--stage` | `twin step` without `--stage` while the record is absent or not trusted: `<why>, and there is no stage to take the next of; give --stage <branch>/<label>` |
| `rehearsal.report.unposted` | warning, 0, none | the proposed change's id | the report could not be posted: `the rehearsal's report could not be posted as a thread on proposed change <id>: <failure>; the status is kept` |
| `platform.unreachable` | rejection, 2 (status `error`), none | `PREFECT_API_URL`'s address | `the orchestrator's platform at <address> did not answer: <cause>; make prefect-server starts it`, or `… answered <status>`, a `401` adding `; PREFECT_API_AUTH_STRING must be the credential the platform was started with` |

`api.unreachable`, `api.token.refused`, `api.version.unknown` and `api.transfer.too_large`
are the core's client's ([cli.md](cli.md), "The client's own failures"), which the
orchestrator's client of the core files in the same words; a Python socket error words the
cause of `api.unreachable` where Go's did.

## The documents

Each command's document is a findings document, `findings_version` `1`, held to
[findings.schema.json](findings.schema.json) with the schemas of its `$id` prefix, under the
operation the table above names: `twin.rehearse`, `stage.list`, `stage.plan`,
`intent.read` and `schema.check` keep their names as the orchestrator's operations (020's
R-13), so a check's conclusions read unchanged, and the schema's operation enum keeps them
for the orchestrator's documents though the core answers none of them. Its JSON is written
as Go's `MarshalIndent` writes it, its text as `WriteText` renders it.

- **The `stages` and `plan` blocks** are [stages.schema.json](stages.schema.json)'s, and
  **the `rehearsal` block** [rehearsal.schema.json](rehearsal.schema.json)'s. Both schemas
  are the orchestrator's since 020: their files and their `$id`s
  ([D-055](../docs/decisions.md#d-055)) stay in `contracts/`, beside the core's, the move
  one of ownership. `stages.schema.json`'s `$defs/step` is also the core's `twin.diff`
  block ([api.md](api.md), "020: runs by identity and the diff"), whose pair the plan
  carries between each two stages.
- **The `stage` block** of a create, a step or a read is the stage resolved, as at 014.
- **The rehearsal's report**: its text, and its markdown, at most 4,092 bytes, the comment's
  bound, rendered from the document and the plan's steps by
  `fylgja_orchestrator.documents.rehearsal`, held byte for byte to the goldens captured from
  the Go renderer under `orchestrator/tests/golden/`, but for `fylgja-cli` in the reproduce
  lines and the stages' times.
- **The deadline** is 015's: each compiled stage's budget summed from the packages its
  manifest names, against the ceiling of 3,600 s (`rehearsal.deadline.unfit` over it).

## The adapter

The Infrahub reader as a tool of its own, in Python
(`orchestrator/src/fylgja_orchestrator/adapters/infrahub/`, on `infrahub-sdk` 1.23.2):

```text
python -m fylgja_orchestrator.adapters.infrahub read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] --out <f> [--json]
python -m fylgja_orchestrator.adapters.infrahub stages [--branch <b>] [--scope tag:<n>] [--json]
python -m fylgja_orchestrator.adapters.infrahub schema-check --branch <b> [--json]
```

- `read` is `fylgja intent read` as the core's server ran it: the guards, the scope, the
  packages, the credentials, the probes (the file, else `FylgjaProbe` on the default
  branch, else none), the stage's resolution, the read through the schema library's DCIM at
  `opsmill/schema-library@26336e9` by [D-057](../docs/decisions.md#d-057)'s mapping, then a
  snapshot `2` ([snapshot.schema.json](snapshot.schema.json)) written to `--out`, **byte for
  byte the file the Go reader wrote but for its `observed_at`**, so its `snapshot_id` is the
  same; it files nothing. `stages` is `stage list` without the twin's row, `schema-check` is
  `schema check`. The flows call the same three functions.
- It prints the success lines on stdout and the findings as text on stderr, or the document
  alone under `--json`, and exits by the status. `read` and `stages` print a start-up line on
  stderr, never the token: `fylgja-infrahub: reading <address> as <reader>@<version>, scope
  <scope>`.
- A missing `INFRAHUB_ADDRESS` or `INFRAHUB_API_TOKEN` is `operation.failed` about the
  operation before anything is read.

## The flows and their platform

**The platform** is a Prefect 3.8.8 server on the lab host (`make prefect-server`), its
database under `local/orchestrator/prefect`, listening at `PREFECT_API_URL`,
`http://<bridge>:4200/api`, the host's Docker bridge address, one listener the host's
processes and Infrahub's task workers both reach. Its API takes basic authentication, the
server's `PREFECT_SERVER_API_AUTH_STRING`, which `make prefect-server` sets from
`PREFECT_API_AUTH_STRING`; every client of the platform sends that `<user>:<password>`
(the task workers as `FYLGJA_ORCHESTRATOR_AUTH`, [checks.md](checks.md)). The core's token
never crosses the bridge.

**The runner**, `fylgja-orchestrator serve` (`make orchestrator-serve`), serves six flows,
each as its deployment `main`, its entrypoint the flow's module path:

| Flow (deployment) | Parameters | The command |
|---|---|---|
| `intent-read/main` | `branch`, `at`, `stage`, `scope`, `probes_path`, `out` | `intent read` |
| `twin-create/main` | `branch`, `stage`, `scope`, `probes_path`, `dry_run` | `twin create` |
| `twin-step/main` | `stage`, `scope`, `probes_path`, `allow_restart`, `wait`, `dry_run` | `twin step` |
| `stage-plan/main` | `branch`, `scope`, `probes_path` | `stage plan` |
| `twin-rehearse/main` | `branch`, `scope`, `probes_path`, `markdown` | `twin rehearse` |
| `schema-check/main` | `branch` | `schema check` |

A parameter left out is the flag not given. Its start-up line names the platform and the six
deployments, never the credential: `fylgja-orchestrator: serving intent-read/main,
twin-create/main, twin-step/main, stage-plan/main, twin-rehearse/main, schema-check/main on
the platform at <PREFECT_API_URL>`. With no `PREFECT_API_URL` it refuses to start, `fylgja-orchestrator:
PREFECT_API_URL is not set: the runner serves the orchestrator's platform, which make
prefect-server starts`, exit 2, and with a platform that does not answer its credential,
`platform.unreachable`'s sentence, exit 2. Its deployments carry no schedule, and are not
paused when it stops.

**A flow run's document is its artifact**: every flow ends by writing its findings document
as the run's artifact of type `fylgja-findings`, key `fylgja-<flow>-<flow run id>`, `data`
the document's JSON, and returns it. Its out lines are the run's log records under the
logger `prefect.flow_runs.fylgja`, apart from Prefect's own lines. A check reads both
([checks.md](checks.md)).

**How a flow reaches the core**: as a client of the API ([api.md](api.md)), on
`FYLGJA_API_ADDRESS` (default `127.0.0.1:7650`) with `FYLGJA_API_TOKEN`, each read where a
request is built and held nowhere. **Every run is started under `detach`** and then read by
`run.read` every 2 s to its document; the answer stream is never opened, and a flow run
again after its platform restarts reads the run it started rather than starting a second
into `run.in_flight`. A dry run is never detached. No `Expect: 100-continue` is sent.

### The rehearse flow

`twin-rehearse` is 015's rehearsal re-made over the core's operations, the workflow
`fylgja-rehearse` gone from the core (020's research §5.18):

1. the plan, `stage-plan`'s, and the baseline rule: the first compiled stage is the
   baseline, each compiled stage after it rehearsed, the branch point refused `scope.empty`
   at `read` alone passed over, any other refused stage refusing the rehearsal;
   `rehearsal.steps.none` for one compiled stage alone;
2. the deadline, `rehearsal.deadline.unfit` over the ceiling;
3. the host: a run of the core's in flight refuses it (`run.in_flight`); a twin the record
   names as its own dead rehearsal's (the record's flow is `twin-rehearse` and the platform
   reads its run `FAILED`, `CRASHED` or `CANCELLED`, or no longer knows it) is destroyed
   first, `rehearsal.twin.reclaimed`; then the core's dry run of the baseline's create,
   whose host check refuses any other twin (`host.twin.present`);
4. the run: the baseline created and verified with `--wait`, each rehearsed stage stepped
   to with `--allow-restart` and classified against the baseline's findings, stopping at
   the first whose verdict stops the run; the record follows the twin after each create and
   step; last, `twin.destroy`, whatever happened, unless the baseline's create could not
   start because a run holds its identity.

The deadline is kept on the flow's own clock from its start: once it passes, the core's run
in progress is interrupted by `run.interrupt` and read to its end, the stage is `error`,
`rehearsal.deadline.cut`, and the destroy follows; nothing cuts the destroy. The flow's
`timeout_seconds` is **4,020 s**, the allowance before the start (300 s), the ceiling
(3,600 s) and the destroy (120 s), which `fylgja-twin`'s `timeout` less its margin covers. A
timeout or a cancellation reaching the flow is the cut or the cancellation of the stage in
progress, and the destroy and the report still follow; the runner kills a cancelled flow's
process 30 s after its SIGTERM, so the flow reads the destroy for 20 s and bounds the post
to the rest.

**The report** is posted by the flow on the proposed change as one `CoreChangeThread`
holding one `CoreThreadComment`, its text the markdown, both written on the default branch
through the SDK with the adapter's credential ([D-053](../docs/decisions.md#d-053), its
thread kept by D-065); a thread whose comment cannot be saved is deleted. A refusal because
the host is held is not posted, since a check asks again while it is held; a post that fails
is `rehearsal.report.unposted`, the status kept.

## The record and the store

Under `FYLGJA_ORCHESTRATOR_ROOT` (default `local/orchestrator`), files and no database:

- **`snapshots/<id>.json`**: every snapshot the orchestrator takes, filed once by a link
  from a temporary sibling, as the core's store files them: an entry is whole or absent and
  never overwritten, and a second take of the same snapshot writes nothing. A corrupt entry
  is refused, never replaced.
- **`twin.json`**: the one record of the twin the orchestrator last drove, written whole by
  `twin-create`, `twin-step` and `twin-rehearse`, by a temporary sibling renamed into place:

  ```json
  {"record_version": "1",
   "stage": {"branch": "change-1", "label": "first-link", "at": "2026-10-29T10:00:00.000000Z"},
   "proposed_change": {"id": "18a6…", "branch": "change-1"},
   "snapshot_id": "0940db93…", "flow_run_id": "6c1e…", "flow": "twin-create",
   "written_at": "2026-10-29T10:05:12.123456Z"}
  ```

  The core's `twin.json` `12` names no stage ([cli.md](cli.md), "020: runs by identity and
  the diff"), so this is what the stage list's twin row, the step's default target,
  `stage.twin.moved` and the reclaim read. **It is trusted only while `twin show`'s
  `show.record.snapshot_id` is its `snapshot_id`**; otherwise `record.twin.stale` and
  `step.target.required` above. Once a create's or a step's run has ended, `twin show` is
  asked again: the record is written when the twin stands at the snapshot sent, removed
  after a create from a branch, whose twin names no stage, and left as it was otherwise (a
  dry run, a refusal, a diverged step, a failed create, a core that cannot be asked).

## Environment

| Variable | `fylgja-cli` and the flows | The runner | The adapter as a tool | The checks |
|---|---|---|---|---|
| `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` | yes | through its flows | yes | no |
| `FYLGJA_DEFAULT_SCOPE` | yes | through its flows | yes | no |
| `FYLGJA_PSP_DIR` (and `FYLGJA_PSP_SHIPPED`, the shipped packages' directory when installed elsewhere) | yes | through its flows | yes | no |
| `FYLGJA_API_ADDRESS`, `FYLGJA_API_TOKEN` | yes | through its flows | no | no |
| `FYLGJA_ORCHESTRATOR_ROOT` | yes | yes | no | no |
| `PREFECT_API_URL`, `PREFECT_API_AUTH_STRING` | yes | yes | no | no |
| `PREFECT_HOME` | yes, when `PREFECT_API_URL` is unset | yes | no | no |
| `FYLGJA_ORCHESTRATOR_ADDRESS`, `FYLGJA_ORCHESTRATOR_AUTH` | no | no | no | yes ([checks.md](checks.md)) |

No credential, token, password or configuration line reaches an out line, a document, a log
record or an artifact. The core reads none of the orchestrator's variables, and the
orchestrator none of the core's server's but the API's two.

## Formats and versions

| Format | Version | |
|---|---|---|
| findings | `1` | [findings.schema.json](findings.schema.json), the core's and the orchestrator's |
| the API, as a client | `1` | [api.md](api.md) |
| snapshot, probe declaration | `2`, `1` | taken by the adapter, read by the core ([snapshot.schema.json](snapshot.schema.json), [probes.schema.json](probes.schema.json)) |
| the orchestrator's record | `1` | above |
| Prefect | 3.8.8, with `fastapi` 0.150.0 | `orchestrator/pyproject.toml`; Python 3.14 |
