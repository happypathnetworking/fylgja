# data-model.md

Every type, document, format and identifier `020-core-orchestrator-split` adds, moves or
retires, to [the template](../../docs/templates/data-model-template.md). The decisions are
[research.md](research.md) §2; the shapes on the wire are in [contracts/](contracts/).

## 1. The API's run operations (`internal/api/wire.go`, `internal/server`, `contracts/api.schema.json`)

- **`detach`** (bool, default false) joins the `args` of `twin.create`, `twin.provision`,
  `twin.step` and `twin.destroy` (R-03). Under it the answer is `start`, `run` and the
  `document` (status `ok`, one finding `run.detached`, info, step `start`, message `run
  <workflow_id> <run_id> started; read it with fylgja run read`). With `dry_run` it is
  refused `run.flags.conflict` before any guard. `twin.destroy`'s detached answer carries
  a `run` frame, which its stream never did.
- **`run.read`** (`/v1/run/read`, R-04): args `workflow_id` (one of `fylgja-provision`,
  `fylgja-step`, `fylgja-destroy`), `run_id` (optional). Frames: `run` gains `state`
  (`running`, `completed`, `failed`, `cancelled`, `terminated`, `timed_out`), then the
  `event`s so far, then the `out` lines under `render`; a running run's answer ends there
  by EOF; an ended run's ends with the `document` (operation `run.read`, `subject.run_id`,
  the run's findings from its result). `run.unknown` (error, exit 1) names the identity.
- **`run.interrupt`** (`/v1/run/interrupt`): the same args; answers a document with
  `run.cancel.requested` (info) after `CancelWorkflow`, or `run.ended` (error) when the
  run has closed, or `run.unknown`. No stream, no body file.
- **`twin.diff`** (`/v1/twin/diff`, R-05): args `from`, `to`, each an id of the store or
  the path of a file sent (`files in`: the snapshot files named); the answer's document
  `twin.diff` carries `snapshot_from`, `snapshot_to`, `bundle_from`, `bundle_to` and a
  `step` block, `step.Pair` as `twin.step`'s dry run writes it (`contracts/step.schema.json`),
  or `unchanged: true`; a refused compile answers the compile's findings at step
  `compile`. Files both snapshots and both bundles, starts nothing.
- **Lost**: `twin.rehearse`, `stage.list`, `stage.plan`, `intent.read`, `schema.check`
  leave `api.Operations`, `handlers` and `operationArgs`; `branch`, `at`, `stage`,
  `scope` and `probes` leave `twin.create`'s and `twin.step`'s args, so each is the
  transport `400` "takes no argument". `api.schema.json`: the `start` frame's
  `workflow_id` enum loses `fylgja-rehearse`; `$defs/run` gains `state`; the request's
  `args` gains `detach`, `from`, `to`, `workflow_id`, `run_id`. API version `1`, unmoved;
  a frozen copy of 016's `api.schema.json` goes under `internal/{server,cli}/testdata/contracts/016-probes/`
  as the earlier features' did.

## 2. The twin record `12` (`internal/lab/twin.go`, `internal/lab/wire/types.go`, `contracts/twin.schema.json`)

`twin_version: "12"`. Gone: `stage` (`StageRef`), `step.to.stage`, `rehearsal`
(`RehearsalRef`). Kept: `lab`, `snapshot_id`, `bundle_id`, `provenance {branch, at,
schema_hash, scope, mapping}`, `observed_at`, `observed_at_note`, `source`, `run`,
`provisioned_by`, `recorded_at`, `nodes`, `state`, `step {…, wait, loss}` (R-06). The
step's rule compares the twin's filed snapshot's `envelope.scope` and `envelope.mapping`
with the target's, `step.twin.unsteppable` naming both; `stepNoTarget` goes, since a step
always names a snapshot. A record of `11` or earlier reads as today (`ReadRecord` gates
no version) and is refused a step by `stepScopeUnknown`'s rule extended to `< 12`: "the
twin was created from a record version this build no longer steps (twin.json N); fylgja
twin destroy clears it". `twin show` loses its stage line; the kinds stand. Frozen copy:
`twin.schema.json` `11` under `internal/{lab,server,cli}/testdata/contracts/016-probes/`.

## 3. The worker (`internal/provision`)

`NewWorker` registers `Provision`, `Destroy`, `Step`; `Rehearse`, `RehearseInput`,
`RehearseResult`, `rehearseStartOptions`, `StartRehearse`, `ResultOfRehearse`,
`StartReclaim`, the rehearsal branches of `InFlight`, `historyStep`, `StartDestroy` and
`wire.RehearsalRef` go; `TestWorkerRegistersEveryScheduledActivity` pins three workflows
and seventeen activities; `determinism_test.go` drops `workflow_rehearse.go`; the seven
histories replay unchanged. `provision.Service` gains `Describe(ctx, workflowID, runID)`
(state for `run.read`), over `DescribeWorkflowExecution`.

## 4. The snapshot (`internal/snapshot`, `orchestrator/src/fylgja_orchestrator/adapters/infrahub/snapshot.py`)

Unchanged, `2`. The Python side carries `normalize(ctm)` (the sorts and defaults of
`ctm.Normalize`), `hashed_bytes(snapshot)` (the Go structs' key order, `json.dumps(…,
indent=2, ensure_ascii=False)` with `<`, `>`, `&`, U+2028 and U+2029 escaped as Go does,
plus `\n`) and `snapshot_id()` = SHA-256 hex; `write(path)` writes the full document as
`Marshal` does (`snapshot_version`, `snapshot_id`, `observed_at`, `ctm`, `probes`). Tested
against `0940db93…` (tier 2), `testdata/snapshot/*.json`'s ids and a Go-written file of
each (tier 1, the files copied into `orchestrator/tests/data/`).

## 5. The adapter (`orchestrator/src/fylgja_orchestrator/adapters/infrahub/`)

Modules: `client.py` (`infrahub-sdk` 1.23.2, `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`,
the branch in the path, `at` only when given, `X-INFRAHUB-KEY`), `schema.py` (`GET
/api/schema`, conformance against `mapping.py`'s kind table, `schema.*`), `read.py`
(the eleven queries carried from `queries.graphql`, the mapping to CTM `2`, fidelity rows,
`scope.*`, `platform.*`, `intent.at.precision`, `artifact.*`, completeness), `stamps.py`
(D-058 to D-060), `events.py` (D-048), `stages.py` (`Ref`, `find`, `resolve`, `order`,
`stale`, `main_moved`, `twin_moved`, `list`, the `stages` block), `probes.py` (the file,
else `FylgjaProbe` on the default branch, else none; `probes 1`; an empty file declares
none), `packages.py` (`platform.matches` from `psp/*.yaml`, `FYLGJA_PSP_DIR` override),
`validate.py` (`Intrinsic`'s rules), `__main__.py` (`read`, `stages`, `schema-check`;
exit by status; `--json`). Its findings document is the core's `findings 1`, rendered by
`fylgja_orchestrator.documents`.

## 6. The orchestrator's documents (`orchestrator/src/fylgja_orchestrator/documents/`, `contracts/orchestrator.md`)

`findings.py` (the document, `findings 1`, its text form as `internal/findings` renders
it), `stages.py` (the `stages` block, `stages.schema.json` owned here, its file unmoved in `contracts/`), `plan.py` (the
`plan` block), `rehearsal.py` (the `rehearsal` block, the verdict rules of
`rehearsal.Classify`, `NewFindings`, `Stop`, `Build`; the text; the markdown with
`CommentMax` 4,092; `Reproduce` writing `fylgja-cli twin create --stage … --scope …`,
`fylgja-cli twin step --stage … --allow-restart`, `fylgja-cli twin verify`, `fylgja-cli
twin destroy`), `deadline.py` (`Deadline`, `Fits`, `Ceiling` 3,600 over the node plans
of each compiled bundle). Goldens under `orchestrator/tests/golden/` (R-14).

## 7. The flows (`orchestrator/src/fylgja_orchestrator/flows/`)

Six `@flow`s, deployment `main` each, parameters as their `fylgja-cli` flags: `intent-read
(branch, at, stage, scope, probes_path, out)`, `twin-create (branch|stage, scope,
probes_path, dry_run)`, `twin-step (stage?, scope, probes_path, allow_restart, wait,
dry_run)`, `stage-plan (branch, scope, probes_path)`, `twin-rehearse (branch, scope,
probes_path, markdown)`, `schema-check (branch)`. Each ends by writing its findings
document as the flow run's artifact `fylgja-findings` (key `fylgja-<flow>-<run id>`,
`data` the JSON) and returning it. `core.py` is the API client: token and address from
`FYLGJA_API_ADDRESS`/`FYLGJA_API_TOKEN`, every run `detach: true` then `run.read` every
2 s, the stream never opened; `api.unreachable`, `api.token.refused` as the CLI's.
`twin-rehearse`'s body: plan, reclaim (§8), baseline, each stage's step and verify,
verdicts, report, post; `timeout_seconds` the deadline; `finally`: destroy and the
report's cut (`rehearsal.deadline.cut`).

## 8. The orchestrator's record and store (`orchestrator/src/fylgja_orchestrator/record.py`)

`FYLGJA_ORCHESTRATOR_ROOT/snapshots/<id>.json` (filed once by `os.link`, as the core's
store) and `FYLGJA_ORCHESTRATOR_ROOT/twin.json`: `{"record_version": "1", "stage":
{"branch", "label", "at"}, "proposed_change": {"id", "branch"}, "snapshot_id",
"flow_run_id", "flow", "written_at"}`. Trusted while `twin.show`'s `show.record.snapshot_id` equals
`snapshot_id`; else `record.twin.stale`. The reclaim reads `flow_run_id` from `GET
/api/flow_runs/{id}` (R-09).

## 9. The checks' glue (`infrahub/checks/fylgja_api.py`, `contracts/checks.md`)

`FYLGJA_ORCHESTRATOR_ADDRESS` (`host:port`), `FYLGJA_ORCHESTRATOR_AUTH` (`user:password`,
basic auth); `trigger(flow, parameters) -> flow_run_id` (`GET
/api/deployments/name/<flow>/main`, `POST …/create_flow_run`, one retry on `503`),
`wait(flow_run_id, deadline) -> state` (poll 5 s), `document(flow_run_id)` (artifacts
filter, `data` parsed), `cancel(flow_run_id)` (`set_state CANCELLING`); the R-15 retry
and margins unchanged; `post_comment` removed (the flow's). `fylgja_step.py` asks
`stage-plan`; `fylgja_twin.py` skips a draft, asks `twin-rehearse`, concludes from
`status`.

## 10. The host (`scripts/infrahub/docker-compose.override.yml`, `local/.env`, `scripts/bring-up.sh`)

The override's `task-worker.environment` becomes `FYLGJA_ORCHESTRATOR_ADDRESS:
host.docker.internal:4200` and `FYLGJA_ORCHESTRATOR_AUTH: ${FYLGJA_ORCHESTRATOR_AUTH}`;
`.env.example` and `local/.env` gain `FYLGJA_ORCHESTRATOR_AUTH`, `FYLGJA_ORCHESTRATOR_ROOT`,
`PREFECT_API_URL` (`http://<bridge>:4200/api`) and `PREFECT_API_AUTH_STRING`; the server
loses the bridge `--listen`; the part `orchestrator` starts `prefect server` and
`fylgja-orchestrator serve` (R-17).

## 11. The identifiers (`internal/findings/finding.go`, `orchestrator/src/fylgja_orchestrator/documents/rules.py`)

- **Added to the core**: `run.detached` (info, `start`), `run.unknown` (error),
  `run.cancel.requested` (info), `run.ended` (error), `run.flags.conflict` (error);
  operations `run.read`, `run.interrupt`, `twin.diff` in `findings.schema.json`'s enum.
- **Retired from the core** (a `TestTheOrchestratorsRulesAreRetired`): `scope.invalid`,
  `scope.unset`, `scope.empty`, every `stage.*`, `stages.*`, `rehearsal.*`, `schema.*`,
  `intent.*`, `probe.kind.absent`, `probes.*`, `snapshot.flags.conflict`,
  `step.target.unknown`, `step.target.current`, `step.stage.skipped`; operations
  `twin.rehearse`, `stage.list`, `stage.plan`, `intent.read`, `schema.check` leave the
  core's enum and join the orchestrator's.
- **The orchestrator's** (`rules.py`, held to `findings.schema.json`'s pattern by a
  test): every retired rule above with its wording, plus `record.twin.stale` (info),
  `step.target.required` (error, exit 1), `rehearsal.report.unposted` (warning),
  `platform.unreachable` (error, exit 2, the Prefect server), `api.unreachable` and
  `api.token.refused` as the core's CLI words them.

## 12. The documents

- `contracts/api.md`, `api.schema.json`, `cli.md` (the lost commands, `--detach`, `fylgja
  run read|interrupt`, `twin diff`), `twin.schema.json` (`12`), `findings.schema.json`
  (the enums), `step.schema.json` unchanged; new `contracts/orchestrator.md` describing
  `rehearsal.schema.json` and `stages.schema.json`, their files and `$id`s unmoved in
  `contracts/`; `contracts/checks.md`
  moved from 015; the frozen copies of 016's shapes (api, twin, findings) under the three
  packages' `testdata/contracts/016-probes/`.
- `docs/architecture.md` §1, §2, §4.1, §4.4, §4.6, a new §4.7 the orchestrator, §5, §6;
  `docs/c4/workspace.dsl` and `make diagrams`; `docs/glossary.md` (Core, Orchestrator,
  Adapter, Tool, Flow (orchestrator); Client, Server, Rehearsal, Stage, Check (Infrahub));
  `docs/development.md`; `SECURITY.md`; `README.md`; `CLAUDE.md`; `docs/verified-facts.md`
  (a "Prefect 3.9.0" section, Infrahub's embedded Prefect); `docs/brief.md`; the roadmap
  (R-24); `.infrahub.yml` only in its comment on the checks; `.specify/memory/constitution.md`
  3.0.0 and `.specify/templates/plan-template.md`.
