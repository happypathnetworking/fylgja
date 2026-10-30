# research.md

Research for `020-core-orchestrator-split` (F-027), written by the plan on 2026-10-29 to
[the template](../../docs/templates/research-template.md): §1 what was verified on the
development host and in the tree before the design relied on it, §2 the decisions
R-01…R-24 with the requirement each serves, §3 the constitution amendment drafted for the
operator's OK at `analyze` (D-065 and D-066 are already written, so no decision entry is
drafted), §4 what implement must verify or measure, §5 appended by the runs.

## 1. Verified at plan

Each fact was checked on 2026-10-29 on the development host (Ubuntu 26.04.1, Infrahub
1.11.2 as the Compose project `fylgja-infrahub`, Python 3.14.4) or in the tree at
`a3bd43d`. Each lands in `docs/verified-facts.md` once it holds at implement.

### 1.1 Infrahub 1.11.2's embedded Prefect is a separate server, on the Compose network alone

- `local/infrahub/docker-compose.yml:273-292`: the service `task-manager` runs `uvicorn
  --host 0.0.0.0 --port 4200 --factory infrahub.prefect_server.app:create_infrahub_prefect`
  against `task-manager-db` (Postgres 18) and publishes **no port** on the host; `docker
  compose ps` shows ports for `infrahub-server` (8000), `database`, `message-queue` only.
  The host's 4200 is free (`ss -ltn`), so an orchestrator server on the host does not
  collide with it. Its API answers `GET /api/version` `0.8.4` and `POST /api/flows/filter`
  (Infrahub's own flows, `action-add-node-to-group`…) from inside a task worker, with no
  authentication.
- The two task workers are `prefect worker start --type infrahubasync --pool
  infrahub-worker` with `PREFECT_API_URL=http://task-manager:4200/api` (:354, :373). Inside
  `fylgja-infrahub-task-worker-1`: **Prefect 3.7.5** on Python 3.14.7, `httpx 0.28.1`,
  `requests 2.34.2`, `infrahub_sdk 1.11.2` (the image's own, not the `.venv`'s 1.23.2),
  `pydantic 2.12.5`, `yaml 6.0.3`; no `aiohttp`. So the roadmap's assumption holds: the
  orchestrator runs its own Prefect server beside Infrahub's, and a check must not use the
  worker's Prefect client with its environment, which points at Infrahub's server; plain
  HTTP with `httpx`, which the checks already use (015), reaches the orchestrator's.

### 1.2 Prefect 3.9.0 on Python 3.14.4: install, server, basic auth

- PyPI on 2026-10-29: `prefect` latest `3.9.0`; `infrahub-sdk` latest `1.23.2` (the
  `.venv`'s); `pytest` `9.2.0`; `ruff` `0.17.3`. `pip install prefect==3.9.0` into a fresh
  `python3 -m venv` completed with `pydantic 2.14.2`; `prefect version` reports a SQLite
  server (3.46.1). It installs and runs on 3.14.4.
- `prefect server start --host 127.0.0.1 --port 4210 --no-ui` with
  `PREFECT_SERVER_API_AUTH_STRING=fylgja:secret` and `PREFECT_HOME` under a scratch
  directory answered `/api/health` 200 after about 30 s. **The open-source server has
  basic authentication**: without the credential `GET /api/version` and `POST
  /api/flows/filter` are `401`, `/api/health` stays `200`; with `Authorization: Basic`
  (httpx `auth=("fylgja","secret")`, or the client setting `PREFECT_API_AUTH_STRING`) the
  API answers. Its API version is `0.8.4`, the same as Infrahub's 3.7.5 server reports.
- The first `create_flow_run` right after the deployments appeared answered `503 Service
  Unavailable`; the same request a few seconds later answered `201`. A client retries a
  `503` at start (R-14).

### 1.3 A deployment is triggered, polled, read and cancelled over plain HTTP

Two flows served by `serve(flow.to_deployment(name="main"), …)` from one process (the
runner), driven by `httpx` alone:

- `GET /api/deployments/name/{flow}/{deployment}` answers the deployment's `id` within 4 s
  of the runner's start.
- `POST /api/deployments/{id}/create_flow_run {"parameters": {…}}` answers `201` with the
  flow run (`id`, `name`, `state.type` `SCHEDULED`); the runner picked it up and a 1 s
  flow read `COMPLETED` after 14.3 s of polling `GET /api/flow_runs/{id}` (`state.type`,
  `state.name`, `end_time`), the runner's poll interval being most of it.
- `GET /api/flow_runs/<unknown uuid>` is `404`.
- `POST /api/flow_runs/{id}/set_state {"state": {"type": "CANCELLING"}, "force": true}`
  answers `201` `ACCEPT`; the runner ended the run `CANCELLED` 4.1 s later.
- `POST /api/flow_runs/filter {"limit": 50}` lists the runs; nothing locks two runs of one
  deployment, so the core's fixed workflow identities stay the one lock (`run.in_flight`).

### 1.4 A flow's document crosses as a Prefect artifact of a type of Fylgja's own

`Artifact(type="fylgja-findings", key="probe-<run id>", data={…}).create()` inside the
flow was accepted; `POST /api/artifacts/filter {"flow_run_id": {"any_": ["<id>"]}}`
answers it with `type`, `key` and `data`, the dict **serialised as a JSON string** in
`data`. A check reads the findings document that way, and never a flow's return value,
whose persistence would need a result store the container cannot read.

### 1.5 A flow's `finally` and hooks run on a timeout and on a cancellation

- `@flow(timeout_seconds=3)` sleeping 10 s ended `FAILED` named `TimedOut`, message `Flow
  run exceeded timeout of 3.0 second(s)`, after 11.3 s; the flow's `finally` block ran (a
  marker file was written) and the `on_failure` hook ran. The runner's log also shows
  `Engine execution exited with unexpected exception … CancelledError` after the state
  was set, noise and not a failure.
- The API cancellation of 1.3 ran the `finally` block and the `on_cancellation` hook. So
  a rehearsal whose flow times out or is cancelled still reaches its destroy (R-11), with
  one caveat owed at implement (§4): the marker was instant, and a destroy of a minute
  under a cancellation's grace must be measured.
- `prefect.testing.utilities.prefect_test_harness` exists in 3.9.0, for the Python tests
  that need a server of their own.

### 1.6 The tree: what the long-operation shape and the removal rest on

- **Events are already built from history.** `internal/provision/client.go:929-1040`:
  `Follow` long-polls `GetWorkflowHistory` and derives every `event` frame; there is no
  query handler, signal, search attribute or memo; results come from `GetWorkflow(…).Get`
  (`Result` :1276, `ResultOfStep` :452), which reads the completion event. The server keeps
  nothing (`contracts/api.md`, "The event"). A read of a run by identity is the same
  `Follow` and `Result` over a run the request names, not a new mechanism (R-04).
- **The interrupt**: `internal/server/follow.go:247-292`: the first interrupt asks
  `CancelWorkflow`; the second stops waiting (`run.cancelled`, exit 2); a client that
  closes its connection cancels nothing; termination happens only in `awaitFirstTask`
  before a worker took the run. The interrupt by identity reuses `requestCancel`'s path.
- **The 015 defect goes with the rehearse workflow** (the brief's reading, confirmed):
  `Follow` follows a child synchronously on `CHILD_WORKFLOW_EXECUTION_STARTED`
  (`client.go:1010-1013`), and the only workflow that starts children is `Rehearse`
  (`workflow_rehearse.go`, `ParentClosePolicy ABANDON` in `options.go:291-298`). Provision,
  step and destroy start none, so with `Rehearse` gone no `Follow` can block on an
  abandoned child.
- **The seven replay histories are provision's and step's**
  (`internal/provision/testdata/*.history.json`, `workflow_replay_test.go`), none the
  rehearsal's, which is covered by testsuite tests alone (`workflow_rehearse_test.go`,
  `TestRehearse*`); FR-008's "every remaining history replays" is the seven unchanged.
- **`internal/rehearsal` leaves whole.** The worker imports it for `Classify`, `Stop`,
  `Ceiling` and `Mechanism` from `workflow_rehearse.go` alone; the server for the
  deadline, the report and the markdown. With `Rehearse` gone nothing in the core needs
  it, so it is removed after the Python port of its verdict, deadline and renderers is
  held to the captured goldens (R-13, R-14). The baseline rule and the reclaim are the
  server's (`internal/server/rehearse.go:141-198`, `:489-568`), re-made in the flow.
- **An unknown argument is a transport `400`**, `the request is not one: <op> takes no
  argument "<name>"` (`internal/server/handlers.go:55-88`), no finding id, which the CLI
  files as `operation.failed`; the five lost arguments fall under it once they leave
  `operationArgs`.
- **The deadline's budgets are in the bundle**: `rehearsal.Deadline` sums
  `lab.NodePlans` of each filed bundle (`internal/server/rehearse.go:241-258`), so the
  flow reads them from `twin.compile`'s files (R-10), no package loaded.
- **The reclaim is server-side, not the workflow's**: `internal/server/rehearse.go`
  (`rehearsing.host`, `reclaim`) reads `twin.json`'s `rehearsal.workflow_id ==
  fylgja-rehearse` and calls `StartReclaim` (`client.go:609-626`), which destroys. The
  orchestrator re-makes it over its own record and Prefect's run state (R-09), and the
  core's `twin.json` `12` carries no rehearsal block.
- **The checks are httpx and the SDK alone** (`infrahub/checks/fylgja_api.py:14-21`):
  no Prefect import; the 4,092-byte comment cut is the server's
  (`internal/rehearsal/markdown.go:19-22`, `CommentMax`), so it moves to the Python
  renderer. `fylgja-twin` posts the thread through SDK node creates (`post_comment`,
  `fylgja_api.py:380-428`); the rehearse flow takes that code over.
- **The CLI ignores `event` frames** and prints the server-rendered `out` lines
  (`internal/cli/send.go:109-212`, `internal/server/console.go`); `--json` re-indents the
  document frame. `TestClientReachesTheCoreThroughTheAPIAlone` is
  `internal/compiler/purity_test.go:268`, allowing `internal/cli` to reach `internal/api`,
  `internal/findings` and `internal/tree` alone. `cmd/fylgja-fixture` imports
  `internal/ctm`, `internal/probe` and `internal/testsupport` only, never the reader.
- **Tier 3's case 9 is Temporal-shaped in one helper**: `rehearsal_run`
  (`scripts/e2e.sh:2140-2163`) parses ``Run `fylgja-rehearse <id>` `` from the comment and
  reads the rehearsal's and its children's Temporal histories; the reproduce block it
  asserts verbatim (:2386-2390) names `fylgja twin create --stage …`. Both move to the
  orchestrator's shapes (R-19). The script's own server is started with a token it makes
  and `--listen 127.0.0.1:0` (:976), and every client call carries only `PATH`, `HOME`,
  `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` (:360-368).
- **The snapshot id in Python** was reproduced by the NetBox spike
  (`docs/verified-facts.md`, 10-29): SHA-256 of `json.dumps(body, indent=2) + "\n"` in the
  contract's key order with the lists sorted as `ctm.Normalize` sorts them; compact and
  sorted-key forms do not match. The adapter's normaliser is held to `0940db93…` (R-07).

## 2. Decisions

- **R-01 The platform is Prefect 3.8.8, pinned, on Python 3.14, with a server of the
  orchestrator's own.** Verified in §1.1-1.5 on 3.9.0; moved to 3.8.8 by the operator on
  2026-10-29 (T013), since 3.9.0 and `infrahub-sdk==1.23.2` need disjoint `whenever`
  ranges, with `fastapi==0.150.0` pinned beside it, on which §1.2 holds (§5.7); §1.3-1.5
  are re-verified on 3.8.8 where T025 and T026 first lean on them. The server runs `prefect server start
  --host <bridge address> --port 4200 --no-ui` with `PREFECT_HOME=local/orchestrator/prefect`
  (SQLite, the open-source default) and `PREFECT_SERVER_API_AUTH_STRING` from
  `local/.env`'s new `FYLGJA_ORCHESTRATOR_AUTH` (`<user>:<password>`, made by the bring-up
  script); uvicorn takes one host, and the host's own processes reach the bridge address
  as containers do, so one listener serves both. Nothing of Prefect's beyond the
  open-source server is used (no automations, events, pause-for-input, work pools: the
  runner is `serve()`). *Alternatives*: `0.0.0.0`, rejected as every interface; two
  servers, one per address, rejected as two databases. Serves FR-017, FR-022, FR-005.
- **R-02 The orchestrator's layout** (FR-017, FR-026): `orchestrator/` holds
  `pyproject.toml` (package `fylgja_orchestrator`, console script `fylgja-cli`, a second
  `fylgja-orchestrator` for `serve`), `src/fylgja_orchestrator/{adapters/infrahub,
  documents, flows, core.py, record.py, cli.py, serve.py}`, `tests/` (`pytest`, tier 1 by
  default, tier 2 under the marker `contract`, goldens under `tests/golden/`), and its
  venv at `orchestrator/.venv` with a `.gitignore` of `*` inside, as the root `.venv`
  has, made by `make orchestrator-venv` (`python3 -m venv` and `pip install -e
  'orchestrator[dev]'`). The root `.venv` stays the operator's `infrahubctl` alone. Linter
  `ruff 0.17.3` (E, F, W, B, SIM, as the checks were linted ad hoc), test runner `pytest
  9.2.0`; `infrahub-sdk==1.23.2`, the `.venv`'s. `make test` runs `go test` then
  `orchestrator/.venv/bin/pytest -q orchestrator -m 'not contract'`; `make lint` adds
  `ruff check orchestrator infrahub/checks`; `make test-contract` adds `pytest -m
  contract` after the Go packages; `make orchestrator-serve` and `make prefect-server`
  start the two new processes; CI's unit and lint jobs gain `actions/setup-python` (3.14)
  and the same commands. The shipped `psp/*.yaml` are read from the repository root
  (`FYLGJA_PSP_DIR` as the override, the same variable as the core's), found from the
  package by its installed path's parent or by `FYLGJA_PSP_SHIPPED` when installed
  elsewhere (§4). *Alternative*: the orchestrator in the root `.venv`, rejected since it
  would pin the hand tool to the orchestrator's dependencies.
- **R-03 The core's detached start is the argument `detach`** (FR-009), boolean, on
  `twin.create`, `twin.provision`, `twin.step` and `twin.destroy`. Under it the answer is
  `start`, `run` (for destroy, whose stream opens none, `run` is written for the detached
  answer alone), then the `document` frame, status `ok`, carrying one finding
  `run.detached` (info, step `start`) naming the identity, so the contract's "the last
  frame is the document" stands. A refusal before the start is the document, as today.
  `dry_run` with `detach` is `snapshot.flags.conflict`'s successor `run.flags.conflict`.
- **R-04 The read and the interrupt by identity are `run.read` and `run.interrupt`**
  (FR-010), `/v1/run/read` and `/v1/run/interrupt`, args `workflow_id` (one of the three
  fixed ids) and `run_id` (optional: the workflow's latest run when absent). `run.read`
  answers `run` with a `state` (`running`, `completed`, `failed`, `cancelled`,
  `terminated`, `timed_out`), then every `event` so far from `Follow` and, under `render`,
  the `out` lines the stream would have printed; while the run runs the answer ends
  there, by EOF, with no document (the spec's US4 scenario 2), the one answer the contract
  lets end without one; once it has ended, the `document` frame follows, operation
  `run.read`, its findings the run's own (`Result` or `ResultOfStep` from the completion
  event), status by the run's outcome. An identity no run has is `run.unknown` (error,
  exit 1) after `DescribeWorkflowExecution` alone. `run.interrupt` asks `CancelWorkflow`
  as the stream's first interrupt does and answers a document with `run.cancel.requested`
  (info); on an ended run, `run.ended` (error). The stream stays as it is for the core's
  CLI, which gains `--detach` on the four commands and `fylgja run read|interrupt`.
  **The API version stays `1`**: 019 removed arguments without a move, pre-1.0; the five
  lost paths answer the contract's existing `404` wording, which is already "no operation
  at this path"; a move to `2` would move every client and 72 frozen copies for no new
  meaning. *Alternative*: a callback, out by the brief.
- **R-05 The step between two snapshots is `twin.diff`** (FR-011), `/v1/twin/diff`, args
  `from` and `to`, each a filed id or a path sent as a file as `twin.compile` takes one;
  the server validates and files each snapshot as on create, compiles each on the
  goldens' path, files both bundles, and answers the document `twin.diff` with the
  `step`'s plan block as `twin.step`'s dry run shapes it (`contracts/step.schema.json`:
  nodes added, removed, changed; links; artifacts moved), `unchanged` when the two
  bundle ids are one; a refused compile answers the compile's own findings. Nothing is
  deployed or started. *Alternative*: the plan showing ids alone, rejected by the brief.
- **R-06 `twin.json` `12`** (FR-007): the `stage` block, `step.stage` and `rehearsal` go;
  `snapshot {id, branch, at, observed_at}`, `bundle_id`, `scope`, `mapping` and the rest
  stay as `11` had them. The step's rule reads the twin's filed snapshot (by
  `snapshot.id` under `snapshots/`) and the target's: `envelope.scope` and
  `envelope.mapping` (`reader`, `model`, `version`) must equal, else
  `step.twin.unsteppable` naming both pairs; a twin whose record names no snapshot
  (`from_bundle`) is unsteppable as 019 has it. `11` and earlier are read by the existing
  version gate: shown with their version, refused a step naming `twin destroy`, destroyed.
- **R-07 The adapter is the package `fylgja_orchestrator.adapters.infrahub`, a tool with
  one command shape** (FR-012 to FR-016): `python -m fylgja_orchestrator.adapters.infrahub
  read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] --out
  <file> [--json]`, `… stages --branch <b> [--scope]` (the `stages` document) and `…
  schema-check --branch <b>`, each exiting by its document's status; `fylgja-cli` calls
  the same functions. Its start-up line: `fylgja-infrahub: reading <address> as <mapping
  reader>@<model version>, scope <scope>`, never the token. It ports `internal/intent`
  (the queries, the mapping, conformance and completeness, the `scope.*`, `schema.*`,
  `platform.*`, `intent.*` and `probes.*` rules), the reader's half of `internal/stages`
  (reference `<branch>/<label>`, resolution to `(branch, at)` under D-045 to D-048, the
  list, `stage.*` and `stages.*`) and `internal/stage`'s read-and-take; it validates the
  CTM as `validate.Intrinsic` does before writing, and leaves probe placement to the
  core, which refuses a sent snapshot it cannot place (016). The snapshot's id is SHA-256
  of `json.dumps(body, indent=2) + "\n"` with the contract's key order and
  `ctm.Normalize`'s sort, a Python `normalize` tested against the fixture's `0940db93…`,
  `testdata/snapshot/*`'s ids and the goldens' three. `infrahub-sdk==1.23.2`; queries
  sent through the SDK's `execute_graphql` with the Go reader's query strings carried
  over, under `infrahub-common`'s GraphQL rules where this repository does not decide
  otherwise (the branch in the path, `at` only when supplied, `GET /api/schema` first).
- **R-08 The flows** (FR-018 to FR-020): `intent-read`, `twin-create`, `twin-step`,
  `stage-plan`, `twin-rehearse` and `schema-check`, each `@flow` with that name and a
  deployment `main` served by `fylgja-orchestrator serve` (one process, the runner);
  `fylgja-cli` runs the flow function in its own process, recorded on the platform when
  `PREFECT_API_URL` is set, so no runner is needed for a hand command and a run exists for
  the record. Every call to the core is `detach: true` then `run.read` polled every 2 s,
  so a flow rerun after a restart reads the run it started (its identity is in the flow's
  log and the record) rather than starting a second. `twin create --dry-run` passes
  `dry_run` to `twin.create` with the snapshot file, and the CLI prints the `out` lines.
- **R-09 The orchestrator's state** (FR-021): `FYLGJA_ORCHESTRATOR_ROOT` (default
  `local/orchestrator`) holds `snapshots/<id>.json`, filed once, never overwritten, and
  `twin.json`: `{record_version: "1", stage: {branch, label, at}, proposed_change: {id,
  branch}, snapshot_id, flow_run_id, flow, written_at}`, written by the create, step and
  rehearse flows, read beside `twin.show` and trusted only while `twin.show`'s
  `show.record.snapshot_id` equals `snapshot_id`; distrusted, `stage list` prints `record.twin.stale` (info) and no twin
  row, `twin step` without `--stage` is refused `step.target.required` (error). The
  reclaim: `twin.show` names a twin at the record's snapshot, and `GET
  /api/flow_runs/{flow_run_id}` is a `twin-rehearse` run whose state is terminal
  (`FAILED`, `CRASHED`, `CANCELLED`) or `404` after the platform's retention: the twin is
  its own dead run's and is destroyed with `rehearsal.twin.reclaimed` naming the run; any
  other case is the host held (`host.twin.present`), never reclaimed.
- **R-10 The rehearsal's deadline** (FR-019): the plan's compiled bundles carry each
  node's package and budgets in the manifest (`twin.compile`'s files), from which the flow
  derives the deadline as `rehearsal.Deadline` did (the mechanism's per-stage sum and the
  ceiling, 3,600 s), with `rehearsal.deadline.unfit` unchanged; `timeout_seconds` on the
  flow is that deadline, and the destroy sits in the flow's `finally` (§1.5). `fylgja-twin`'s
  `timeout` 4,260 stands; the flow's overhead is measured at implement (§4).
- **R-11 The report is posted by the rehearse flow** (FR-019, FR-024): the thread and
  comment creates move from `fylgja_api.py` into the flow (the SDK, `main`), the 4,092-byte
  cut with the markdown renderer; the document is published as the flow run's artifact
  `fylgja-findings` (§1.4); the check reads it. A rehearsal that cannot post logs
  `rehearsal.report.unposted` (warning) and keeps its status.
- **R-12 The checks' glue** (FR-024): `fylgja_api.py` becomes the orchestrator's client:
  `FYLGJA_ORCHESTRATOR_ADDRESS` and `FYLGJA_ORCHESTRATOR_AUTH` from the override (the two
  variables that replace `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` there), basic auth on
  `httpx`, `GET /api/deployments/name/<flow>/main`, `POST …/create_flow_run` (retried
  once on `503`), `GET /api/flow_runs/{id}` every 5 s to a terminal state, the artifact's
  `data` parsed as the document, `set_state CANCELLING` at the deadline; the R-15 retry
  while held and the margins stay as 015 set them. `fylgja-twin` concludes from the
  status and posts nothing.
- **R-13 The documents move**: `rehearsal`, `stages` and `plan` blocks, their text and
  the markdown, rendered by `fylgja_orchestrator.documents` from the Go renderers'
  goldens, `fylgja-cli` in the reproduce lines; `contracts/orchestrator.md` describes them
  and `api.md` stops, `rehearsal.schema.json` and `stages.schema.json` staying where they
  are in `contracts/` with their `$id`s (D-055) and the frozen copies' glob unmoved, the
  move one of ownership (settled at `analyze`); the checks'
  contract moves to `contracts/checks.md`. The findings document's `operation` keeps the
  names (`twin.rehearse`, `stage.list`, `stage.plan`, `intent.read`, `schema.check`) as
  the orchestrator's operations, so the checks' conclusions read unchanged.
- **R-14 The goldens' capture is a live task before any removal**: on the attended
  loop's host, a throwaway proposed change with three stages through the fixture tool, then
  `fylgja stage list --json`, `stage plan --json`, `twin rehearse --json` and `--markdown`
  with their text, saved under `orchestrator/tests/golden/`; a session that cannot boot a
  twin captures `stages` and `plan` alone and leaves `rehearsal` to the live run.
- **R-15 Tier 2's shape** (FR-028): the Go contract tests of `internal/intent`,
  `internal/stages`, `internal/stage` and the server's Infrahub-reading handlers go with
  their packages once the Python port has been compared; `internal/checks` stays Go;
  `internal/cli`'s tests of lost commands go. The Python tier 2 (`pytest -m contract`)
  holds the ported assertions, a compare test that runs the Go `fylgja intent read` and
  the adapter on the fixture and on a throwaway branch and diffs the files byte for byte
  (removed with the Go reader), and the flow tests against the real Infrahub and a core
  server started by the test with no `INFRAHUB_*`. Wall time is measured at implement;
  `internal/stages`' 1,713 s leaves the Go tier.
- **R-16 Tier 3** (FR-029): `scripts/e2e.sh` runs `fylgja-cli` for every command naming a
  branch or a stage, with `FYLGJA_ORCHESTRATOR_ROOT=$OUT/orchestrator` and no
  `PREFECT_API_URL`, so the flows run under Prefect's ephemeral server in `PREFECT_HOME=$OUT/prefect`
  (owed §4), against the script's own core server; case 9 goes through the operator's
  platform on the bridge, its precheck a `GET /api/health` and an authenticated
  `/api/deployments/name/twin-rehearse/main` from inside a task worker; `rehearsal_run`
  reads the flow run and the core's Temporal runs by the identities the report names;
  the credential greps add Prefect's home and the orchestrator's logs.
- **R-17 The bring-up script's part `orchestrator`** (FR-026): installs the venv, writes
  `FYLGJA_ORCHESTRATOR_AUTH` into a new `local/.env` (kept byte for byte when present,
  with a note when the name is absent, as `FYLGJA_DEFAULT_SCOPE` was), starts the Prefect
  server and the runner detached logging to `local/prefect.log` and
  `local/orchestrator.log`, and recreates nothing of Infrahub's: the override's change
  reaches the task workers by the live session's `up -d` (the brief's operator steps).
- **R-18 The core's listener**: `fylgja serve` with no `--listen` stays `127.0.0.1:7650`;
  the bring-up script's `serve` loses the bridge `--listen`; the "not a loopback" warning
  stays for anyone who asks.
- **R-19 Identifiers**: data-model §11. Retired from the core: every `scope.*`, `stage.*`,
  `stages.*`, `rehearsal.*`, `schema.*`, `intent.*`, `probes.*` rule, `snapshot.flags.conflict`,
  `step.target.*`'s stage forms. Added to the core: `run.detached`, `run.unknown`,
  `run.cancel.requested`, `run.ended`, `run.flags.conflict`. Added to the orchestrator:
  `record.twin.stale`, `step.target.required`, `rehearsal.report.unposted`,
  `platform.unreachable` (the Prefect server), `api.unreachable` kept for the core.
- **R-20 The constitution amendment is 3.0.0** (FR-025), drafted in §3.
- **R-21 Which Infrahub skills**: none designs a kind; `infrahub-managing-checks` is read
  before `fylgja_step.py` and `fylgja_twin.py` change; `infrahub-common`'s GraphQL
  references and `infrahub-managing-transforms`' union-fragment rule before the adapter's
  queries are written. Where they say `uv run`, branch-first or `infrahubctl check`, this
  repository decides otherwise (`CLAUDE.md`).
- **R-22 The estimate is 24–36 hours** of sessions, re-made from the route the plan
  draws (plan.md, "Order of the work"): the core 5–7 (R-03 to R-06, the removal), the
  adapter 9–13, the orchestrator 7–10, the tiers and documents 3–6. The route is expected
  at T001–T095, inside 017's T121; if `tasks` draws past 121, the cut is between the
  adapter's port (a spec of its own, leaving the Go reader as the orchestrator's tool
  until the port lands) and the rest, and the plan proposes it then, not now.
- **R-23 `make command-log` and the loop** are untouched; the orchestrator's tests run
  in the loop's pure gate through `make test`.
- **R-24 The roadmap's reconciliation** is the route's first documents task (FR-032):
  F-027's row (Prefect, the reader ported, after F-014, 24–36), Release 0.3's total
  49–75, item 5 linking here.

## 3. Drafted for the operator

### 3.1 No decision entry

D-065 and D-066 were appended at feature-open (`docs/decisions.md:4099-4238`); each
superseded entry's status line was written with them. The chain writes none.

### 3.2 Constitution 2.3.0 → 3.0.0 (MAJOR: Principle I redefined in its scope)

Sync Impact Report line: `2.3.0 → 3.0.0 (2026-10-29, MAJOR: Principle I redefined in its
scope). Fylgja is two deployables (D-065): I binds the core and frees the orchestrator;
III binds every reader, now an adapter of the orchestrator; VI's "where the source cannot
replay time" names the adapter and the orchestrator's store (D-066); VIII and IX are the
core's, IX adding the orchestrator's files; X binds both; XI names the orchestrator as a
client. Development Workflow: the repository gate reads "a single Go module, one binary,
for the core; the orchestrator a Python project under orchestrator/". Templates:
.specify/templates/plan-template.md's Constitution Check names 3.0.0 and its rows I, III,
VI, VIII, IX and XI read the amended text.`

- **Preamble**: "builds a walking twin of it" gains "as two deployables: a core that runs
  a twin from a snapshot, and an orchestrator that reads the sources, resolves stages and
  rehearses (D-065)".
- **I. Go, End to End, for the Core.** "Fylgja's core MUST be a single-language Go system
  … one static binary that is CLI, worker and API server. … The orchestrator is not bound
  by this principle: it is a Python project on Prefect that calls tools written in
  anything and reaches the core through the API alone (XI)." Rationale adds D-065.
- **III**: "A reader is an adapter of the orchestrator; it MUST read one source's model …
  and write a snapshot, the core's one input (D-061)". The Infrahub-owned kinds list
  stands. Rationale adds D-065.
- **VI**: the last sentence reads "Where the source of truth cannot replay time, the
  snapshot's id addresses intent, and a stage there is the snapshot the adapter took when
  the operator marked it, held by the orchestrator (D-066)".
- **VIII**: first sentence gains "in the core"; adds "The orchestrator MUST drive the
  core through the API and MUST NOT start a workflow of the core's."
- **IX**: adds "The orchestrator's state is Prefect's own run history and files under its
  state root, the snapshots it took and one record of the twin it drove; neither
  deployable introduces a database without a decision-log entry."
- **X**: unchanged but for "in either deployable" after "a log line".
- **XI**: "The CLI is a client, and so is every later one: the orchestrator, a web UI, an
  agent surface, a check running inside Infrahub, which is the orchestrator's client. …
  no command of the core's CLI runs the core in its own process". Rationale adds D-065.
- **Gate Adjustments**: unchanged.
- **Development Workflow, Repository**: "The core is a single Go module, one binary,
  `internal/lab` as the host-bound boundary; the orchestrator is a Python project under
  `orchestrator/` with its own tests and lint, in this repository. (D-018, D-015, D-065)".
  **Three test tiers** gains "the orchestrator's pure tests run with the pure tier; its
  contract tests with the contract tier".

## 4. Owed at implement

- Prefect's ephemeral server for tier 3's cases 1 to 8 (`PREFECT_SERVER_ALLOW_EPHEMERAL_MODE`,
  a `PREFECT_HOME` under `$OUT`) and for `prefect_test_harness` in tier 2: verify a flow
  runs with no `PREFECT_API_URL`, and how long its first start takes (R-16).
- A destroy of a minute inside the flow's `finally` under an API cancellation: whether the
  runner's grace lets it finish, and the setting that lengthens it if not (R-10, §1.5).
- Which of the bundle's files carries the node plans' budgets the flow reads (R-10), and
  whether `twin.compile`'s document should carry them instead.
- The flow's overhead between `create_flow_run` and the flow's first request to the core,
  and between its end and the artifact's visibility, against `fylgja-twin`'s margins
  (R-12); the runner's poll interval (`PREFECT_RUNNER_POLL_FREQUENCY`) if 14 s is too slow.
- Tier 2's wall time whole, and the Go tier's once `internal/stages` leaves it (R-15).
- The adapter's package data: how the installed package finds `psp/*.yaml` (R-02).
- The adapter's read time of the fixture against the Go reader's.
- The goldens captured (R-14): the branch names and ids they carry, and the renderer's
  test that substitutes them.
- Each fact of §1 re-verified where the build changes it, then written to
  `docs/verified-facts.md` under a new "Prefect 3.9.0" heading and Infrahub's.
- The measured effort against R-22.

## 5. Verified at implement

Appended by the runs.

### 5.1 The goldens captured (T003, Run 3, 2026-10-29)

On the worker and the server restarted from this tree at `96d38d8` (the same code as 016's
`195af3a`: no Go, `go.mod`, `contracts/`, `probes/` or `psp/` change between), both
binaries live, every login and `INFRAHUB_*` name in their environments, `free -m` 17,122 MiB
available before and 17,241 MiB after, no tier running. Saved under
`orchestrator/tests/golden/`, whose `README.md` names every id below and how each file was
made.

- **The branch and the change**: `fylgja-test-golden-41263`, seeded with the three-node
  fixture in 55.4 s; the draft `18e3127c-025b-f488-33be-c5158cf576c3` opened by `-propose`
  in 80.7 s, its five validators concluded, `fylgja-step` and `fylgja-twin` `success`
  (the twin skipped as a draft). Three stages: `seeded` (1.6 s), `-add-link` (2.1 s, n1's
  and n3's checksums moved 9.1 s after), `third-link` (0.7 s), then the third stage on a
  further change, 015's push-refused `bad-port`: `-add-interface n1:ethernet-1/99
  -generate` (4.6 s, n1's checksum moved 7.8 s after), `bad-port` (0.6 s). The task line
  leaves the further change open. A refused push makes the rehearsal cover every verdict
  (refused, baseline, passed, failed, not reached) and the reproduce lines FR-023 names.
- **The reads**: `stage list` 3.8 s (`--json`) and 4.3 s, exit 0, five rows; `stage plan`
  14.7 s and 15.0 s, exit 1, the branch point refused `scope.empty` as tier 3's case 9
  expects of it, `bad-port` and `head` each warned `artifact.interface.unrepresented`;
  `twin create --stage …/seeded` 66.0 s, bundle `ce705cdb…`; `stage list` with its
  `← twin` row 4.8 s and 4.4 s, the record's stage `seeded`; `twin destroy` 2.6 s.
- **The rehearsal**: asked once through the API under `render: "markdown"`, whose last
  frame carries the document, its text and the markdown (`contracts/api.md`), about 95 s
  wall (18:15:10Z to 18:16:45Z). Run `fylgja-rehearse 01a188df-b883-70f8-8999-bc18b484dc1f`
  ended `nonconforming`, 74.5 s of the 2,580 s deadline: `bad-port` diverged at the push
  (`push.refused` on n1), `head` not reached, the twin destroyed. Every stage's snapshot and
  bundle id agrees with the plan's. Its markdown, 3,486 bytes, is `Markdown`'s shortened
  form, since the whole form is 4,271 bytes. The task names the posted thread, which
  only a check posts, and a check's re-run would have been a second rehearsal whose
  answer is not kept. So this run's markdown was posted by the check's own `post_comment`
  (`infrahub/checks/fylgja_api.py`), and the `CoreThreadComment` read back by GraphQL
  equals it byte for byte.
- **Rendered from the JSON** by a throwaway test in `internal/rehearsal`, deleted after:
  `StageLines` and `Closing` equal the tail of the `out` frames; `WriteText` equals the
  frame's `text`; `Markdown(document, plan.json's steps)` equals the frame's markdown; and
  `WriteJSON` of the decoded document equals the frame's document re-indented, which is
  `--json`'s output. So the markdown is a function of `rehearsal.json` and `plan.json`'s
  `steps` alone, which is what T022's renderer takes. `rehearsal.full.md` is `Markdown`'s
  whole form for the same inputs.
- **The substitution the renderer's test makes**: none for a renderer fed these documents,
  which must give these bytes but for `fylgja-cli` in the reproduce lines
  (`rehearsal.reproduce`, `rehearsal.txt`'s indented lines, the markdowns' fenced block). A
  live run's branch, change, `at`s, ids, run ids and timings are its own. The one edit to
  the captured bytes is the state root, read `<state-root>` in `rehearsal.json` and
  `rehearsal.out.txt`, a path under the user's home that no renderer writes.
- **After**: `fylgja-fixture -branch … -delete` (10.8 s) removed the three stages, the
  proposed change with its thread and validators, and the branch; `CoreProposedChange`,
  `FylgjaStage`, `FylgjaProbe`, `CoreChangeThread` and `CoreUserValidator` 0 on `main`,
  `Branch` `main` and `fylgja-fixture` alone, hash `8a4f3bee…`, `fylgja` at `842c893`, as
  T001 found them; `clab inspect --all` `{}`, no `local/twin`, no running workflow, no
  Schedule. Nothing under `testdata/` changed.

### 5.2 A run read and interrupted by its identity (T007, Run 7, 2026-10-29)

- **The describe, on the dev server** (Temporal CLI 1.9.1, Server 1.32.0, read only): a run
  id the workflow holds no run under answers NotFound (`workflow execution not found for
  workflow ID "fylgja-provision" and run ID "…"`), a run id of no run's shape answers
  InvalidArgument (`Invalid RunId.`), a workflow id never run NotFound (`workflow not found
  for ID: …`), and no run id the latest run, `COMPLETED`. `Describe` reads NotFound and
  InvalidArgument alike as `*UnknownRunError`, `run.unknown`; any other failure is the
  service unreachable, `run.service.unreachable`.
- **What the Service gained beyond `Describe`**: the task's `Follow` and
  `Result`/`ResultOfStep` serve an ended run, whose history ends at its close so `Follow`
  returns without waiting; three more were needed and are Service methods beside them.
  `History` is `Follow` without its long poll (one `follow(…, wait)` under both), since
  `Follow` on a running run waits for its close and a running read must end at the events
  so far. `InputOfStep` reads the step's input from its history's first event, as
  `towards` does, because `StepDocument` is built from the input beside the result.
  `ResultOfDestroy` reads a destroy's result, which no method read: `StartDestroy` read it
  from its own handle. `RunState` is a struct (workflow id, run id, state) rather than the
  state alone, so a read that names no run learns the latest run's id for its
  `subject.run_id` and its history reads.
- **The recorded runs all close `completed`**: each of the seven histories ends
  `WORKFLOW_EXECUTION_COMPLETED` with a result, a cancelled run included, since the
  workflows answer a cancellation with a result. So a read's state says how the workflow
  service closed the run, and the document how the run ended: `cancel-during-host-check`
  `error`, the three other cancelled provisions `failed`, `step-cancelled` and
  `step-diverged` `diverged`, `step-wait-cancelled` `ok` (stepped, its wait cancelled). A
  run closed without a result (failed, terminated, timed out at the service) reads as the
  operation failing at the step its history reached.
- **Decided in the run, from R-04 and data-model §1**: `workflow_id` is required on both
  operations, its absence the transport's `400` as `twin.provision`'s bundle is, since the
  CLI's `--workflow` always gives it; a workflow id outside the three (`fylgja-rehearse`
  among them) is `run.unknown` naming it, before anything is dialled. US4's scenario 6 says
  a read of a destroy has "no `run` frame"; R-04, data-model §1 and contracts/README.md give
  every `run.read` answer the `run` frame with its `state`, and the read follows them: what
  the scenario holds is that the events and the document are the destroy's own, not those of
  a run the destroy cancelled first, which a read by identity never reads. The `out` lines
  begin `run <workflow_id> <run_id>: <state>`, then the events' lines and, once ended, the
  stream's own closing lines (the twin's, the step's, the destroy's cleanup).
- **The client**: `api.Client.RunRead` and `RunInterrupt`; `Answer.Next` is `io.EOF`, not
  `*Cut`, where a `run.read` whose `run` frame said `running` ends at a whole line.
- **Left to T012**: `contracts/api.schema.json`'s `$defs/run` holds `additionalProperties:
  false` without `state`, so the read's `run` frame is held to it by no test yet; the event
  and document frames are. The CLI's answer test covers both operations through answers
  of the document alone (an unknown read, an ended interrupt) for that reason, and its
  command walk leaves out `run.read` and `run.interrupt` until T009 adds the commands.

### 5.3 A run started detached, and the core's CLI over the identity (T008, T009, Run 8, 2026-10-29)

- **Decided in the run, from R-03 and data-model §1**: `detach` is carried on the request's
  options, set by the four runs' handlers, so `runProvision` (create, from a read or a
  snapshot, and provision) and `runStep` answer at the run once `startRun` returns. An
  interrupt that reached the start was the operator's before the run was detached from, so
  under it the run is followed and asked to cancel as the stream asks; otherwise the answer
  is `start`, `run`, then the document. A create's document carries what `carried` always
  put on it (the snapshot, the bundle and the read's and compile's findings), and a step's
  the command's warnings, each before `run.detached`, as a followed run's carry them, so
  "the one finding" of data-model §1 is the one the detach adds. `run.flags.conflict` is
  the first thing `runCreate`, `runTwinProvision` and `runTwinStep` do, its object
  `dry_run`, its words the CLI's flags (`--detach is meaningless with --dry-run: a dry run
  starts no run to detach from`), as `snapshot.flags.conflict`'s are.
- **The destroy**: `provision.Service` gains `StartDestroyDetached`, `StartDestroy` that
  returns once a worker has taken the destroy run, or once it has attached to one in
  flight, with no `Follow` and no result read (`destroy`'s `follow` argument). What it
  cancels first, a rehearsal, a provisioning or a step run, it still waits for, since the
  destroy run starts only once those have closed: their progress is the detached answer's,
  as the stream's, and never an event of the destroy's own. The detached answer writes the
  `run` frame the destroy's stream never wrote.
- **The CLI**: `--detach` on the four commands, sent as `detach`; `fylgja run read` and
  `fylgja run interrupt` send `workflow_id` as `--workflow` gives it, an empty one included,
  which the server refuses `run.unknown` (no cobra-required flag, since every guard is the
  server's), and `run_id` only when `--run` is given. `send` reads `Answer.Next`'s `io.EOF`,
  which only a running `run.read` yields (§5.2), as the command's end: exit 0, nothing
  printed under `--json`.
- **Tests**: `internal/server/exit_test.go`'s shape test holds each of the four detached
  answers to `start`, `run`, `document` with no event of the run and each frame to
  `api.schema.json`; a running `run.read`'s documentless end is §5.2's. The CLI's
  `run_test.go` walks quickstart §3's five lines through the harness.

### 5.4 The step between two snapshots (T010, Run 9, 2026-10-29)

- **The goldens' step names n1 changed, by its bootstrap**: from `three-node` (`b9db37f8…`,
  bundle `c70589c3…`) to `three-node-probed` (`aef03f5d…`, bundle `5222063b…`) the step is
  `nodes: +n1-loop-a; +n1-loop-b; ~n1 (bootstrap)`, `links: +n1-loop-a:eth1 — n1:e1-10;
  +n1-loop-b:eth1 — n1:e1-11`, `artifacts: unchanged`. The two goldens' `configs/n1.cli`
  differ by `set / interface ethernet-1/10 admin-state enable` and `… ethernet-1/11 …`,
  which 016's compile writes for the two ports a probe's hosts take, so the "no device
  changed" of US5 scenario 1 and T010's line does not hold of the goldens: n1 changes by
  its bootstrap alone, with no image, platform, psp or mapping reason and no artifact
  moved. The goldens must not move (FR-033), so the test asserts the step they give; the
  spec's scenario is the operator's to reword (SC-006's "names the two hosts and their
  links" holds as written).
- **The document**: `snapshot_from`, `snapshot_to`, `bundle_from`, `bundle_to` at its top,
  each once that side resolved or filed, and the `step` block is `step.Pair` as `twin step`'s
  dry run writes it under its `diff`, stages.schema.json's `$defs/step`, each side named
  `snapshot <short>…`, `unchanged: true` inside it: twin.diff has no record, containerlab
  plan or push plan, so step.schema.json's block, which requires them, cannot be its shape.
  `contracts/findings.schema.json` gains the four ids and its `step` is `oneOf` the two
  shapes, which `additionalProperties: false` on both keeps apart; its description gains
  020's line. In Go the block is `findings.StepBlock` with `Pair` set, written alone, and
  read back as a pair when it has no `diff` (`findings` cannot import `internal/step`, and
  two fields under one JSON key would both be dropped).
- **The order of the work**: both sides resolved (`resolveSnapshot`: an id out of the
  store, or the request's file held to `validate.Intrinsic` and filed), then the packages
  loaded, then each compiled on twin compile's path (`stage.Compile`) and its bundle filed
  (`fileCompiled`), so an unknown id refuses before any compile. A side that resolves to the
  snapshot the other did is compiled once. The text prints each side's line and its
  snapshot's stored line at resolve, each bundle's stored line once filed, then the pair's
  text, so a refusal's text names what it left filed. The compiles' warnings are each named
  once, a warning both sides give being the same finding of the same object. Files: a file
  for each of `from` and `to` that is not an id, under its path, a path both name sent once;
  any other shape is `operation.failed` before anything is parsed (`diffFiles`), and the
  CLI never sends one. Nothing is dialled: every test runs with `useService(t, nil)`.

### 5.5 The API's schema and the contracts' gained shapes (T012, Run 11, 2026-10-29)

- **What the schema holds as the server does**: `run.read`'s and `run.interrupt`'s
  `workflow_id` is `required` in their args, since the server answers its absence `400`
  (§5.2), and is any string, since a workflow outside the three is the server's
  `run.unknown`, a `200`, never the transport's; `run_id` is optional. `twin.diff`'s `from`
  and `to` are optional on the wire, each missing one the server's `operation.failed`, as
  `stage.plan`'s `branch` is. `state` is an enum of the six `provision.RunState` values,
  and the `run` frame without it writes no key (`omitempty`), so every other operation's
  `run` frame is unchanged. The `start` frame's enum keeps `fylgja-rehearse` until T034.
- **A test that keeps the two together**: `TestOperationArgsAreTheContracts`
  (`internal/server`) reads `$defs/args/$defs` and requires each operation's properties to
  be `operationArgs`' names, of the kind the server decodes; run against the schema before
  this run it names the three operations and four `detach`es missing.
- **The answers through a real server**: `internal/cli`'s answer test holds every frame of
  its cases to `$defs/frame`; it gains a detached create (`start`, `run`, `document`) and an
  ended `run.read` (`run` with `state: completed`, the events, the document, no `start`),
  the second failing against the schema before this run. A running read is not among them,
  since the harness's cases each end with a document; its `run` frame is the same shape.
- **The contracts' text** quotes the sentences the code writes (`run.detached`,
  `run.cancel.requested`, `run.ended`, `run.flags.conflict`, `diffFiles`' two, the
  `workflow_id` `400`) and the text the tests assert (quickstart §3's running read, the
  goldens' diff); `api.md`'s and `cli.md`'s rows for the operations the orchestrator takes
  are T036's.

### 5.6 `twin.json` `12` and the step's rule from the envelopes (T011, Run 10, 2026-10-29)

- **Decisions taken within R-06**: a step given neither `--snapshot` nor `--stage` is
  refused before anything is read (`noTargetGiven`: `step.target.unknown`, at resolve, its
  object `--snapshot`), since no record names a stage to take a next one from; the record's
  bundle, its object until 019's R-08, would need the record read. A twin whose snapshot the
  store does not hold is `step.twin.unsteppable`, its object the id: the envelope the rule
  reads is absent. A stage target's envelope is its filed snapshot's (`built.SnapshotID`),
  read from the store as the twin's is.
- **What goes with the blocks until T034/T035**: the rehearsal's reclaim of a dead
  rehearsal's twin (keyed on the record's rehearsal block), stage list's twin row and
  `stage.twin.moved` from the record's stage, and a provisioning run's `towards` in `twin
  show`'s in-flight line. Step and rehearsal documents write each side's `stage` null; show's
  and verify's documents omit or null the stage and rehearsal, as their schemas allow.
- **Replay**: the seven histories replay unchanged; their payloads' `stage` keys decode to
  nothing and no run branched on them.


### 5.7 The orchestrator's two pins do not co-install (T013, Run 12, 2026-10-29)

- **R-01's and R-02's pins conflict**: `pip install -e 'orchestrator[dev]'` with
  `prefect==3.9.0` and `infrahub-sdk==1.23.2` answers `ResolutionImpossible`:
  `infrahub-sdk 1.23.2 depends on whenever<0.10.0 and >=0.9.3`, `prefect 3.9.0 depends on
  whenever<0.11.0 and >=0.10.5` (on Python ≥ 3.13). §1.2 installed Prefect alone, so the pair
  was never tried. PyPI on 2026-10-29: no `infrahub-sdk` release, pre-releases included,
  admits `whenever` 0.10 (1.22.1 to 1.23.2 all say `<0.10.0`); every Prefect from 3.6.26 to
  3.8.8 says `whenever<0.11.0,>=0.7.3`, and 3.9.0 alone raised the floor to 0.10.5.
- **Prefect 3.8.8 with the SDK 1.23.2** (released 2026-10-06, the last before 3.9.0):
  resolves on Python 3.14.4 with `whenever 0.9.5` and `pydantic 2.14.2`, `pip check`
  clean, `prefect version` 3.8.8, API version `0.8.4` (3.9.0's and Infrahub's 3.7.5's).
  **Its server does not start against the FastAPI pip picks**: 3.8.8 requires `fastapi<1.0.0,>=0.139.0`,
  which resolved to 0.162.0, and `prefect server start` fails at import
  (`concurrency_limits_v2.py`: `TypeError: Body() got an unexpected keyword argument
  'min_items'`); 3.9.0 narrowed it to `fastapi<0.151`, which resolves to 0.150.0. With
  `fastapi==0.150.0` beside 3.8.8, §1.2's facts hold on 3.8.8: on `127.0.0.1:4211` with a
  scratch `PREFECT_HOME` and `PREFECT_SERVER_API_AUTH_STRING`, `/api/health` `200` after
  29 s; `GET /api/version` and `POST /api/flows/filter` `401` without the credential, `0.8.4`
  and `200` with it. §1.3 to §1.5 (deployments over HTTP, the artifact, `finally` on a
  timeout and a cancellation) were not re-run on 3.8.8.
- **Prefect 3.9.0 with the SDK forced onto `whenever` 0.10.5** (installed after it, against
  its requirement): imports, and `Timestamp(...).to_string()` answers, with a
  `WheneverDeprecationWarning` from the SDK's `timestamp.py`; `pip check` fails. Not a
  state `make orchestrator-venv` can make by its pins.
- **The decision is the operator's** (T013's note): R-01's Prefect is plan and research
  text, FR-012's SDK is the spec's. The options: (1) Prefect `3.8.8` with `fastapi==0.150.0`
  pinned beside it, R-01 and plan.md amended and §1.3–§1.5 re-verified on it where the
  flows' runs (T025, T026) first lean on them; (2) Prefect 3.9.0 kept and the adapter on
  `httpx` alone, FR-012's "on `infrahub-sdk`", R-07 and T016 amended (the Go reader and the
  checks already send plain GraphQL); (3) wait for an SDK release admitting `whenever` 0.10.
  Option 1 changes no spec text and keeps the SDK the root `.venv` holds.
- **What T013 built regardless of the pin**, measured with a scratch venv on 3.8.8 and the
  package on `PYTHONPATH` (no install into the tree): the layout's tier 1, six tests, in
  5.7 s wall (`pytest` 2.3 s of it), against 58.0 s of Go (Run 1), so about 64 s whole
  against the 65 s budget; tier 2's two tests green against this host's Infrahub (the
  pinned SDK, and `Branch` on `main` read with the token), writing nothing; `ruff check
  --config orchestrator/pyproject.toml orchestrator infrahub/checks` at E, F, W, B, SIM and
  line length 120 (the checks' longest line) clean. The lane seed (`seed_worktree`) dropped
  its last path, the planner's join leaving the last entry unterminated for `read -d ''`;
  in this tree a `__pycache__/` under `.claude/skills/`, and in `SeedWorktree`'s repository
  `orchestrator/.venv`.

### 5.8 The orchestrator's venv and `make test`'s budget (T013, T014, Run 12 resumed, 2026-10-29)

- **The venv on the operator's pin** (§5.7's option 1): `make orchestrator-venv` on Python
  3.14.4 made `orchestrator/.venv` in 60 s from an empty venv: `prefect` 3.8.8, `fastapi`
  0.150.0, `infrahub-sdk` 1.23.2, `whenever` 0.9.5, `pydantic` 2.14.2, `httpx` 0.28.1,
  `PyYAML` 6.0.3, `pytest` 9.2.0, `ruff` 0.17.3; `pip check` clean. The package's
  `fylgja_orchestrator.egg-info/` under `src/` is ignored by `.gitignore`'s `*.egg-info/`.
- **The gates on it**: `pytest -q orchestrator -m 'not contract'` six passed (1.9-2.3 s by
  `pytest`, 4.2 s wall with the interpreter's start); `-m contract` two passed against this
  host's Infrahub in 0.13 s, writing nothing; `ruff check --config
  orchestrator/pyproject.toml orchestrator infrahub/checks` clean.
- **`make test`, uncached** (`go clean -testcache`), Go then `pytest`: 61.4 s and 60.3 s
  wall at a load of 2.1-3.5, `internal/cli` 42.4 s and 41.8 s of it: under the 65 s budget,
  with the Python share about 4 s, under the 8 s at which the flows import Prefect lazily
  (tasks.md's budget line). T047 decides whether the budget moves once the port's tests land.
- **CI** (T014): `actions/setup-python@v6` at `'3.14'` and `make orchestrator-venv` in the
  lint, unit and contract jobs and in `release.yml` before `make test`; the lint job keeps
  golangci-lint on its action and runs `make lint-python` (ruff alone, the half of `make
  lint` the action does not run). Not yet run on GitHub's runner: the operator pushes, and
  the first pull request or push after it is its check.

### 5.9 The snapshot id in Python (T015, Run 13, 2026-10-29)

- **`adapters/infrahub/snapshot.py`** ports `ctm.Normalize` (its defaults and its five
  stable sorts), the hashed bytes and the stored form over plain dicts: each object built
  in its Go struct's key order, a field tagged `omitempty` left out when empty (`at`,
  `platform.version`, `enabled` when unset, `link`, `artifact` when absent) and a
  provenance of `intent` left out as `omitzero` leaves it, a string Go writes `""` when
  absent written so, an unknown key dropped. Encoded by `json.dumps(…, indent=2,
  ensure_ascii=False)`, the text translated (`<`, `>`, `&`, U+2028, U+2029 to Go's `\u`
  escapes, a lone surrogate to U+FFFD) and a newline added. Besides the task's
  `normalize`, `hashed_bytes`, `snapshot_id`, `write` and `read`: `take(ctm, probes)`
  (`snapshot.Take`, for T017's read to end on), `marshal`, `unmarshal`, `is_id` and
  `SnapshotError` carrying the core's rule (`snapshot.version.unsupported`,
  `snapshot.invalid`, `snapshot.id.mismatch`) and the field. `marshal` holds a snapshot to
  `Marshal`'s invariants but the probes' declaration rules, which `probes.py` (T017)
  holds before the take; `unmarshal` holds `Unmarshal`'s outer shape and the id, not the
  inner CTM's own rules, which `validate.py` (T016) holds.
- **Held to Go's bytes**: the four wrapped fixtures, copied into
  `orchestrator/tests/data/snapshot/` (a test holds each copy to `testdata/snapshot/`),
  read to their ids and written back byte for byte, and taken again from their inner CTM to
  the same file; a fifth, `escapes.json`, written by a new Go test
  (`TestTheOrchestratorsEscapesFixture`, `internal/snapshot/orchestrator_test.go`, with
  `-update`) from a CTM whose strings carry HTML's three, U+2028, U+2029, the control
  characters, DEL and characters beyond the BMP, and whose lists arrive out of order, id
  `38e0ced3…`, the same both ways. Without the translation its id differs, so the fixture
  is the one that catches it. By hand, every one of the 203 snapshots the core filed under
  this host's `local/snapshots/` read to its file name's id (133 of version `1`), and the
  70 of version `2` wrote back byte for byte. Recorded in `docs/verified-facts.md`.
- **Tier 2**: `tests/contract/test_snapshot_id.py` read the core's
  `local/snapshots/0940db93….json` (a `2`) to `0940db93…` and wrote it back byte for byte;
  the orchestrator's tier 2, three tests, green. `make test` uncached 60.0 s at a load of
  about 2, the Python share 43 tests in 2.1 s.


### 5.10 The adapter's client, conformance, packages and intrinsic validation (T016, Run 14, 2026-10-29)

- **`client.py` on `infrahub-sdk` 1.23.2, its sync client.** `InfrahubClientSync`, since
  the adapter's commands and the flows' tasks read one request at a time, as the Go
  reader did; the async `InfrahubClient` would make every caller a coroutine for no
  concurrency used. Built from `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` with every
  setting that matters passed explicitly (the token, `username` and `password` `None`, a
  60 s timeout, no retry, no echo), since the SDK's settings read `INFRAHUB_*` from the
  environment and a `username` there would turn on password login. The SDK is imported
  when the first `Client` is built (its import takes about 1.5 s; the module alone 0.12 s),
  so a command that only words a refusal, and tier 2's collection, pay nothing.
- **Two of the SDK's habits undone** (`docs/verified-facts.md`, Infrahub 1.11.2):
  `execute_graphql` rewrites `at` through its `Timestamp` into UTC with six digits, so a
  subclass's `_graphql_url` sends the operator's value verbatim, form-encoded as Go's
  `url.QueryEscape` did (`+` as `%2B`), and only when given; and its exceptions drop the
  HTTP status, so a `custom_recorder` keeps the last response and each failure is worded
  as the Go reader worded it: `<what> (branch <b>[, at <t>]): HTTP <code>: <Infrahub's
  messages>` (or the status alone for a body that is no error document), a 401 or 403 as
  `the credential in INFRAHUB_API_TOKEN was rejected by Infrahub` / `is not permitted to
  read this branch`, errors under 200 as their messages joined by `; `; a missing branch
  marked (`branch_missing`) on the schema endpoint's 400 and GraphQL's 404 naming it, and
  on nothing else; every message passed through `redact`. The REST read goes through the
  SDK's `_get` (no public GET exists), so tier 1's recorded answers reach the client
  through the SDK's own `sync_requester` hook and the SDK runs whole in every test.
  `get_at` carries the `at` for the object store (T017's artifact read); the schema
  endpoint never does. `check_at_precision` is `CheckAtPrecision`, its words
  (`intent.at.precision`, T017's to file).
- **The start-up line** reads `fylgja-infrahub: reading <address> as
  infrahub-dcim@26336e9, scope tag:<n>`: the task's `<reader>@<model version>` taken as
  the reader at the model's commit, the model's name being the reader's own
  (`startup_line`; T019's `__main__` prints it to standard error).
- **`schema.py` and `mapping.py`**: the table, `SchemaInfo` and `conformance_findings`
  ported field by field, with 017's words (`READS_IT`, the used_by sentences), `Conformance`
  with `verified()` as `findings.Verified` shapes it but `stages` (T018's) and
  `ConformanceError`. Every case of `conformance_test.go` carried over on a copy of
  `internal/intent/testdata/schema-26336e9.json` under `tests/data/schema/`, which a test
  holds to its original, each mutation made as the Go test makes it, the expected words
  literal.
- **`packages.py`: the package-data question (§4) answered.** The shipped packages are
  read as files from the repository's `psp/`, found as `Path(__file__).parents[5]` (the
  editable install `make orchestrator-venv` makes leaves the module in the tree); when the
  package is installed elsewhere, `FYLGJA_PSP_SHIPPED` names the directory, and a load
  that finds none says to set it. `FYLGJA_PSP_DIR` adds override packages shadowing a
  shipped one of the same NOS, as the core's `--psp-dir` does. Nothing is copied into the
  wheel as package data, so the core and the orchestrator read one set of files and
  cannot drift. Only `platform` (id, NOS, `matches`) is read: the core validates packages
  and compiles with them. The survivors are held to `psp.identity.duplicate` and
  `psp.matches.duplicate` with the core's words, so a pair never has two packages; a
  shipped package's path in those words is the file's, where the core's is its embedded
  name `psp/<f>.yaml`. `platform.unmatched`'s words are `completeness.go`'s, `Match`
  quoted by a port of Go's `%q` (`documents/findings.quote`, held to `strconv.Quote` on
  quotes, backslashes, control characters, DEL, U+00A0, U+200B, U+2028 and beyond the BMP).
- **`validate.py`: `Intrinsic` and `compiler.LinkTerminations`, word for word.** Held two
  ways: the Go tests' cases carried over with their expected words (the envelope's forms,
  the empty envelope field named once, the required fields, `at` not required, the empty
  CTM pinned and unpinned, the five link disagreements, the defects split between what
  needs a package and what does not); and a Go-written file,
  `orchestrator/tests/data/ctm/intrinsic.json`, Go's `Intrinsic` findings of every CTM
  beside it (the ten fixtures and twelve defects of `testdata/ctm/` copied, `version-1.json`
  aside since no CTM `1` reaches the rules, and eighteen cases written from
  `three-node.json`, one change each, under `cases/`), written by a new Go test,
  `TestTheOrchestratorsIntrinsicCases` (`internal/validate/orchestrator_test.go`, with
  `-update`), which holds the file to Go's rules after: all 40 equal on the first run.
  `snapshot.normalize` runs first, in place, as `ctm.Normalize` does.
- **`documents/findings.py`** holds `Finding`, `Findings` (`add`, `reject`, `rejected`)
  and `quote` now; the document `findings 1`, its validation and text form stay T019's.
  The rule ids live beside the modules that file them until T019's `rules.py` gathers them.
- **Tier 1**: 246 tests in 4.5 s by `pytest` (203 new); `make test` uncached 64.2 s with
  the SDK imported eagerly and 62.3 s with it lazy, at a load of 1.5-1.8, `internal/cli`
  42.4 s and 41.8 s of it: under the 65 s budget by 0.8-2.7 s, which T047 weighs as the
  port's tests land. **Tier 2**: `tests/contract/test_client.py`, five reads of this
  host's Infrahub (the fixture branch conforms; a missing branch named by the schema
  endpoint, 400, and by GraphQL, 404; a wrong token refused on both and never quoted; a
  pinned `at` with a `+00:00` offset reads `main`), green with the three earlier, eight in
  1.3 s, writing nothing.


### 5.11 The adapter's read, stamps, events and probes (T017, Run 15, 2026-10-29)

- **The skills (R-21).** `infrahub-common`'s GraphQL references and
  `infrahub-managing-transforms`' union-fragment rule apply as the Go reader already applied
  them: a connector, an end and an event are selected by `__typename` with inline fragments
  (`... on DcimCable`, `... on InterfacePhysical`, `... on NodeMutatedEvent`), and the
  branch is in the path; the queries are carried over, not redesigned.
- **The eleven queries** are `adapters/infrahub/queries.py`, one module the read, the
  stamps, the events, the probes and T018's stages share, each a whole document (its
  operation, then the fragment it spreads), sent through the SDK's `execute_graphql` with
  its `operationName`. Held to `internal/intent/queries.graphql` token by token
  (`tests/unit/test_queries.py`, which skips once T035 removes the file) but for
  `__typename`, which genqlient added to every abstract selection itself and the adapter
  writes where it reads it, the event's node among them; genqlient's directives (`bind`,
  `pointer`, `omitempty`) have no Python counterpart, since the adapter decodes plain JSON,
  so an end or an interface of a kind the SDL does not name decodes as any other. The
  read-only rules of `readonly_test.go` (every operation a query, the roots the mapping's or
  the seven named, the fragments' targets, the tag by its filter alone) are carried over.
- **The default branch's endpoint.** The SDK's `execute_graphql` reads `branch_name or
  default_branch`, so a client naming no branch would post to `/graphql/main`; the stages',
  probes' and events' reader is `client.DefaultClient`, whose SDK client's `default_branch`
  is emptied so the request is `POST /graphql`, unnamed, as the Go `StageReader` asked, and
  whose failures name `(the default branch)`. `Client.graphql` takes a per-request `at`
  (T018's validations, pinned at a stage). `ClientError.detail` keeps the cause alone, by
  which the read groups the content fetches that failed alike, as `fetchFailures` did.
- **One difference from the Go read, as T017 words it**: the read ends by
  `validate.intrinsic`, not by `validate.Validate` with the registry as `stage.Read` did.
  The rules that read a package's ports and profiles stay the core's, which runs them on
  the snapshot when it compiles it, so a scope the core cannot build is refused there, under
  the same rules and words, one step later. `stage.dedupe` is ported beside it, for the
  artifact rules' collision. The scope's refusal (`the read names scope "…", which is not
  tag:<name>`) drops the Go sentence's tail about a twin created before 017, which no
  adapter read meets.
- **The packages** gain `config.artifact_name` and `config.artifact_content_types`, the
  read's steps 1 and 4; **the probe packages' formats** are read from `probes/*.yaml`
  beside the shipped `psp/` (the repository's, or `FYLGJA_PSP_SHIPPED`'s sibling) and from
  `$FYLGJA_PSP_DIR/probes/`, as the core's probe registry loads them, `format` alone.
- **Live, read-only, on this host's Infrahub**: the adapter's read of `fylgja-fixture`
  under `tag:fylgja` took the snapshot **`0940db93…`**, the Go reader's (SC-002, ahead of
  T020's tier-2 test); its stamps and its 48 intent events since the branch's
  `branched_from` equal, field for field, what `intent.Client.Stamps` and
  `StageReader.IntentEvents` returned at the same moment through a throwaway Go test
  (deleted). Those answers are recorded under `orchestrator/tests/data/graphql/fylgja-fixture/`
  with Go's outputs (`go-stamps-events.json`), and `tests/unit/test_recorded.py` replays
  them: a real Infrahub's wire shapes, in tier 1.
- **Tier 1's fake** (`tests/unit/dcim.py`) is the Go fake `fakeInfrahub` ported onto the
  SDK's transport hook; `conftest.FakeInfrahub` gains per-operation answers, the unnamed
  `/graphql`, the default branch's `/api/schema` and the object store. The Go tests of
  `project_test.go`, `cable_test.go`, `artifact_test.go`, `storage_test.go`,
  `stamps_test.go`, `events_test.go`, `probes_test.go`, `internal/probe/decl_test.go` and
  `readProbes`' cases of `internal/server/probes_test.go` are carried over by name; the
  three-node, lossy and mixed fixtures each read back to their CTM. Two Go tests keep their
  read half alone: `TestReadOfTwoManagementPortsCompilesOne` and
  `TestManagementCableReachesTheCTM`, whose second half compiles, the core's. Of
  `internal/server/probes_test.go`, the request-shape and pipeline cases (`probesFiles`,
  `probesOf`, the takes of a create and a stage pipeline, the snapshot conflict) stay the
  core's API plumbing. Every ported assertion held against the modules as first written
  but three, each fixed to Go's behaviour: a probe's name is matched whole (Python's `$`
  also matches before a trailing newline, Go's does not); `NaN` and `Infinity`, which Go's
  decoder refuses, make a declaration not a JSON object; and a 401 or 403 whose body the
  SDK's relogin hook cannot read (errors as strings, as the Go test sends, or no JSON) is
  the credential's refusal by its status, where it escaped the client as an
  `AttributeError`. One difference left: a value of the wrong type is named in the
  declaration's findings as compact JSON, where Go quotes the file's own text, so they
  differ only in a spacing or a number's spelling (`1e5`).
- **The SDK's settings built once per process.** Each `InfrahubClientSync` built its
  settings anew, reading the environment and a TLS context of the system's certificates,
  about 32 ms; ~300 clients took tier 1 from 4.5 s to 12.9 s and `make test` to 67.1 s.
  `_sdk_settings(token)` builds them once and each client copies them with its own recorder
  and transport (0.1 ms), the context shared; the fake's package pairs and the tests'
  registries are loaded once too. Tier 1: 454 tests in 5.1 s (208 new); `make test`
  uncached 62.3 s at a load of 1.8-2.2, under 65 s. The orchestrator's tier 2, eight
  tests, green on the new client in 1.2 s.


### 5.12 The adapter's stages (T018, Run 16, 2026-10-29)

- **Two modules.** `adapters/infrahub/stages.py` ports `internal/stages`' ref.go,
  resolve.go, stale.go, list.go, target.go and blocks.go, and the read-and-take of
  `internal/server/resolve.go` and `internal/stage/stage.go` (`read_stage`: the stage
  resolved, then its branch read at its at by `read.read_snapshot`, the resolution's
  warnings first). `adapters/infrahub/stage_reader.py`, beyond the task's files, ports
  `internal/intent/stages.go`'s `StageReader` (the kind's check, the open proposed changes
  with their marks, the orphans, a branch's origin, the validators pinned at an `at`) on
  `client.DefaultClient`, whose failures name `(the default branch)`; the event log stays
  `events.intent_events`. `stages.Stamper` is the server's `intentStamper`: a branch's
  conformance asked once and remembered, a refusal raised as `schema.ConformanceError`.
  The two collaborators keep the Go interfaces' shape (`check`, `proposed_changes`,
  `orphans`, `branch`, `validations`, `intent_events`; `stamps(branch, at, scope)`), so the
  Go tests' fakes port as they are.
- **`stages.multiple` is no rule.** The task's line names it; the core files none: two open
  proposed changes on one source branch, which Infrahub refuses itself, are an error naming
  every id and choosing none (operation.failed), and the port raises `StagesError` in the
  same words. No identifier was added.
- **Instants to the nanosecond.** The core's `ParseAt` reads nine fractional digits and
  compares to the nanosecond, Python's `datetime` to the microsecond, so `parse_at` returns
  integer nanoseconds since the epoch over the core's five layouts (RFC 3339 with a T or a
  space, either naive and read as UTC, and a date), a tenth digit and later cut as Go cuts
  them. `head_at` reads `time.RFC3339Nano` alone, as `HeadAt` does, and writes the stamp's
  own offset (`+00:00` for a `Z`) with six digits.
- **The record a parameter.** `twin_moved` and the listing's twin row take a `RecordView`;
  the orchestrator's record (R-09) is T024's to build it from. Its `scope` judges a head
  record under its own scope, as the core did.
- **Not ported here**: `internal/stages/plan.go` (`Plan`, `Build`), the stage-plan flow's
  and `documents/plan.py`'s; so `TestTargetResolvesUnderTheReferenceRules` checks its
  target's refusal through `resolve_from` rather than `Build`, and `TestBlocksValidate`'s
  plan half waits for the plan. Schema check's `verified.stages` is T019's command;
  `StageKindError` carries `missing` and `extension` for it. `TestStageReaderFromEnv` is
  `client.default_from_env`'s, already tested.
- **The golden.** `tests/data/graphql/stages/golden.json` answers as Infrahub would for the
  golden's proposed change (its id, its three marks' ids, ats and descriptions, its
  branched_from, the branch's latest stamp one microsecond before the head, main holding no
  device, the default branch's schema cut from this host's `main`); the listing through the
  real reader and stamper equals `tests/golden/stages.json`'s `stages` block, and with the
  record of `seeded`, `stages-with-twin.json`'s, no finding in either.
- **Live, on this host's Infrahub**: `fylgja-test-py-stages-869676`, seeded with the
  three-node fixture, proposed (`18e324b6-ea27-79a2-33b0-c5177c673cc7`, draft, 64 s for its
  five validators), marked `seeded`, `-add-link`, `third-link`, and `given` with an
  `as_of` of nine fractional digits (this host's `date` ignores `%6N`, which made the
  `intent.at.precision` case for free). The adapter's listing equals the Go server's
  `stage list --json` (its server ran an earlier build of this branch, whose stage listing
  is unchanged since), and each stage resolved as Go's `stage plan --json` resolved it:
  the branch point, `seeded` and the head at the same ats, `given` refused
  `intent.at.precision` and `third-link` `stage.artifact.stale` on n1 and n3, word for
  word. The adapter's 72 requests are `live.json` (each kept once, the branch schema answers
  as `test_recorded.py` serves them, 29.5 MB cut to 167 KB), with Go's two documents, and
  `test_the_recorded_listing_is_the_go_servers` replays them. Then `fylgja-fixture -delete`
  (3 stages, the proposed change, the branch); `CoreProposedChange`, `FylgjaStage`,
  `FylgjaProbe`, `CoreChangeThread` and `CoreUserValidator` 0, `Branch` `main` and
  `fylgja-fixture` alone.
- **Tests**: `test_stages.py` (141: every pure case of `ref_test.go`, `resolve_test.go`,
  `stale_test.go`, `list_test.go`, `target_test.go` and `blocks_test.go` by its Go name, the
  stamper, `read_stage`, the golden and the live replay) and `test_stage_reader.py` (16,
  `internal/intent/stages_test.go`'s); five mutations of the rules each failed a test.
  Tier 1: 611 tests in 5.2 s (157 new); `make test` uncached 64.5 s at a load of 1.2-2.0,
  `internal/cli` 41.7 s of it; `make lint` clean.

### 5.13 The adapter's commands, the findings document, the rules and the stages text (T019, Run 17, 2026-10-29)

- **The document.** `documents/findings.py` gains `Document` (the operation, the status, the
  subject by `Subject`'s ten fields, the ids and blocks by `Document`'s seventeen keys, each
  in the struct's order and left out when empty, and the findings), `new_document`,
  `error_document` (the server's `fail` and `failAt`), `rule_error_document`, `render` (JSON
  to stdout alone, text findings to stderr), the operations, statuses and exit codes, and
  `Location`. The text is `WriteText`'s and `TextLines`'; the JSON is `MarshalIndent`'s by
  `go_json`: `json.dumps` with `indent=2`, Go's HTML-safe escapes and Go's floats
  (`floatEncoder`: shortest digits, plain from 1e-6 to below 1e21 with no `.0`, else an
  exponent cleaned to `1e-7`), through the pure-Python encoder, since the C one writes a
  float by `float.__repr__` whatever it is given. `validate` holds a document to
  `contracts/findings.schema.json` with every schema of the `$id` prefix added, on
  jsonschema, which Prefect's dependencies carry, imported there alone. `Findings.count_of`
  is `List.Count`; `list.count` keeps its meaning.
- **Held to Go.** Thirty documents under `tests/data/findings/`, one or more of each of the
  sixteen operations, transcribed from `finding_test.go`'s `m2Documents`,
  `TestEveryOperationRendersAValidDocument`, `TestTextRenderingPutsRejectionsFirstAndSummaryLast`,
  `TestTheRunRulesRenderValidDocuments` and `TestATwinDiffDocumentCarriesItsSidesAndItsPair`,
  with a location, an escape and a step case. A throwaway Go test (deleted after) decoded
  each into `findings.Document`: all thirty are the current contract's, `WriteText` equals
  each case's text and `WriteJSON` equals the Python rendering byte for byte (one case, the
  M2 dry run, gained M5's node artifact, which the current contract requires). The four
  documents of `tests/golden/` (stage list's two, stage plan's, the rehearsal's, whose
  floats, nulls and empty lists are all there) decode and write again to their bytes, and
  `plan.stderr.txt` and `rehearsal.stderr.txt` are their text, but for the README's one hand
  edit, `<state-root>`, which Go would have escaped.
- **The rules.** `documents/rules.py`: 74 rules (34 the core keeps), each with its id, severity, exit, steps,
  wording (`finding.go`'s comment, shortened) and whether the core keeps the id. The
  orchestrator's own are `record.twin.stale`, `step.target.required`,
  `rehearsal.report.unposted` and `platform.unreachable`; `api.unreachable` and
  `api.token.refused` are listed as the core's (its client's words, which the orchestrator's
  client of the core files), so the task's "new five" are these four and the API's two,
  none of them yet filed. The retired families are data-model §11's: every `scope.*`,
  `schema.*`, `rehearsal.*`, `probes.*` and `stage.*` rule but M2's `stage.failed`, with
  `intent.at.precision`, `probe.kind.absent`, `snapshot.flags.conflict`,
  `step.target.current` and `step.stage.skipped`. **One departure**: `step.target.unknown`
  is marked kept by the core, since `finding.go`'s 020 comment files it for `twin step`
  without `--snapshot`, though data-model §11 lists it among the retired; R-19's "the
  stage forms" reconciles the two, and T035's `TestTheOrchestratorsRulesAreRetired` should
  leave the id in the core. Tests: every id against the contract's pattern (read from the
  schema), distinct, each rule whole (severity, exit 0 exactly for a non-rejection, steps
  of the enum), every `RULE_*` of the adapter's modules in the table, the kept ones in
  `finding.go` today, the four never there, and a document of each rule valid.
- **The stages text.** `documents/stages.py` renders from the block alone: `list_lines`
  (`printList` and `heading`, the widths by bytes as Go's `len` and the padding by code
  points as `%-*s`, so a non-ASCII branch pads as Go's does), `line` and `resolution`
  (`StageBlock.Line` and `Resolution`), `heading` with the plan's destination and scope for
  T022. `stages.txt` and `stages-with-twin.txt` come back byte for byte from their JSON.
- **The commands.** `adapters/infrahub/__main__.py`: `read`, `stages` and `schema-check`,
  each a function (`read`, `stage_list`, `schema_check`) returning the document and the
  success lines, which `fylgja-cli`'s flows can call, and `main` printing them as the Go
  client did (the lines to stdout in text, the findings to stderr, the document alone under
  `--json`) and exiting by the status. The order and words are `runRead`'s, `runStageList`'s
  and `runCheck`'s: the guards (`--branch or --stage is required`, `--out is required`,
  `stage.ref.invalid`, `stage.flags.conflict`, `intent.at.precision`), the scope, the
  packages, the credentials, the probes (the file, else the kind on the default branch), the
  stage's resolution with its findings at no step (intent read's operations carry none) and
  `intent.at.precision` there still status error, the read, the write; the resolved stage
  and its warnings on every document after the resolution. `stages`' `--branch` is optional,
  as `stage list`'s; `--json` is on all three. The start-up line goes to stderr on `read` and
  `stages`, which read under a scope, and not on `schema-check`, which reads none.
  `client.env_credentials` takes the environment it reads, so a command reads one mapping.
  **Three departures**, each where the core's words named the core's server: `scope.unset`
  reads `no --scope was given and there is no default: name one with --scope tag:<name>, or
  set FYLGJA_DEFAULT_SCOPE where the adapter runs`; an invalid `FYLGJA_DEFAULT_SCOPE` is
  `scope.invalid` naming the variable's value, where the server refused to start; and the
  success line ends `; snapshot <id>` with no `stored at`, the store being the
  orchestrator's record's (T024), and lacks the core's `lossy mappings` and `shared ports`,
  which are its compiler's survey (`compiler.Survey`), not a reader's: T025's `intent-read`
  flow, which prints the line, takes them from the core's compile or drops them. A missing
  `INFRAHUB_*` is `operation.failed` about the operation before anything is read, where the
  server's kind read filed it at resolve about `FylgjaProbe`. A snapshot that cannot be
  written is `operation.failed`, `writing snapshot: <path>: <reason>`, as the client's.
- **Live, read-only, on this host's Infrahub**: `read --branch fylgja-fixture --scope
  tag:fylgja` took 4.0 s and filed `0940db93…`, byte for byte `local/snapshots/0940db93….json`
  (the Go server's) but for the two `observed_at` lines; `schema-check --branch
  fylgja-fixture` equals the Go server's `fylgja schema check` byte for byte, `--json` and
  text; `stages --json` equals `fylgja stage list --json` (no open proposed change); nothing
  written to Infrahub.
- **Tests**: `test_findings.py` (64) and `test_cli_adapter.py` (35: each command's exit,
  stdout, stderr and document on recorded answers, the fixture's read through the fake, the
  kind's probes, the golden listing's text and JSON byte for byte through the real reader,
  sixteen guards refused before any request, the token in no output). Tier 1: 710 tests in
  7.5 s (99 new). `make test` uncached 68.0 s and 67.0 s at a load of 2.1–4.7, `internal/cli`
  43.2 and 42.2 s of it, over the 65 s budget: by the operator's answer (T047's note) the
  budget is 90 s, moved in `CLAUDE.md` and `docs/development.md`. `make lint` clean.

### 5.14 Tier 2, the reader's ported tests (T020, Run 18, 2026-10-30)

- **The harness** (`orchestrator/tests/contract/conftest.py`). Every write is the Go fixture
  tool's, built once per session from this tree (`go build -tags fixture` of
  `./cmd/fylgja-fixture`, which `go run` would compile per call) and run as a subprocess from
  the repository's root with the process's `INFRAHUB_*`; a failure raises with its stderr,
  the token redacted. `FixtureTool.throwaway(label)` seeds `fylgja-test-py-<pid>-<label>`
  (the three-node fixture, `-mixed` or `-schema-only`) and deletes it with `-delete` however
  the block ends, then reads `Branch` to hold it gone. `read_under` is the Go tests'
  `readUnder`: the adapter's `read.read` (conformance, the fetch, the intrinsic rules) under
  a scope, the ReadError when the read could not run. `proxy` is the Go test's recording
  reverse proxy, a `ThreadingHTTPServer` forwarding to the real Infrahub with `httpx` and
  keeping each request's method, path and body. `core` is a core server of the test's own,
  `bin/fylgja serve --listen 127.0.0.1:0` with a token it makes, a temporary state root and
  no `INFRAHUB_*`, its address read from its listen line, as `scripts/e2e.sh` reads it:
  `twin compile --snapshot` dials nothing and files nothing, so the core's half needs neither
  Infrahub nor the workflow service, and the host's server is never asked.
- **The fixture tool's four new flags**, each where a Go test's seeding had none: `-add-device
  <name>:<port>[,…]` (`testsupport.AddDevice` with no tag, platform or group; prints the id,
  which the read names an end outside the scope by), `-add-cable <label>=<dev>:<port>,…`
  (`AddCable`, any number of ends), `-set-platform <dev>=<manufacturer>/<platform>`, `<dev>=`
  taking it away (`SetDevicePlatform`), and `-load-schema-file <path>` (`LoadSchemaFile`,
  which refuses `main`). Each refuses `fylgja-fixture`, a branch outside `fylgja-test-`, a
  second of them and a value not of its form before any request; none renders.
  `docs/development.md` and the glossary name them. `-add-interface`, `-mixed`,
  `-schema-only`, `-probes` and `-delete-probes` already existed.
- **The five files**, each Go test carried over by name: `test_read_fixture.py` (twelve:
  `read_contract_test.go`'s eleven, the first split into the snapshot and the counts as
  Go's two); `test_read_conformance.py` (three); `test_read_defects.py` (one);
  `test_read_probes.py` (two, on one module-scoped seeded branch, since neither changes it);
  `test_schema_check.py` (three). `internal/intent/testdata/dcim-cable-absent.yaml` is copied
  under `orchestrator/tests/data/schema/`, held to its original by `test_schema.py`, since
  the Go file leaves with the reader (T035).
- **What the port asserts beyond Go's, or otherwise**:
  - The fixture's read is the command's (`adapter.read`), which reads the kind, so it holds
    the snapshot id `0940db93…` (SC-002) beside the CTM equal to `three-node.json` but for
    the envelope, as dicts and as the marshalled take.
  - The pinned read goes through the proxy, and every GraphQL request's query string is
    `at=<the at>` exactly, where Go read `cfg.endpoint()`.
  - **The defects are held to the side whose rule each is** (research §5.11: the adapter
    runs the intrinsic rules, the core the package's). The Go reader named all three in one
    pass; the adapter cannot, since its intrinsic rule refuses the read and no snapshot
    reaches the core. So one branch, in two steps: c-far and `n3:console` seeded, the
    adapter's read is clean and writes its snapshot, and the core's compile of it is
    `rejected`, exit 1, with `interface.unmappable.linked` on `n2:ethernet-1/99` and
    `interface.rule.unmatched` on `n3:console` in one pass and no bundle; then c-loop, and
    the read is refused `link.endpoints.same_device` on `n1:ethernet-1/5|n1:ethernet-1/6`
    alone, no file written. Both documents validate against `findings.schema.json`.
  - The kind's case reads through the command four times; the probe-file case runs `main`
    with `--json` through the proxy, no GraphQL body naming `FylgjaProbe`, then the core's
    `twin compile` of the file places n1-loop's hosts on n1's `ethernet-1/10` and
    `ethernet-1/11` and lists them under `fidelity.synthesized`: Go's `twin create --snapshot
    --dry-run` less the host check, which is the core's alone.
  - The schema check's three cases run `main`, text and `--json`, in a scratch working
    directory that stays empty; through the proxy the check asks `/api/schema` and no
    GraphQL, the stage kind's verification included.
- **Live, on this host's Infrahub 1.11.2**, every case green at its first run; then each
  file run alone, no twin up, at a load of 2.6–4.1: `test_read_fixture`
  110.6 s wall (twelve; its two seeded cases 35 s and 38 s of seeding), `test_read_conformance`
  83.0 s (the `DcimCable` removal's rebuild 44.7–51.5 s), `test_read_defects` 57.5 s,
  `test_read_probes` 61.9 s, `test_schema_check` 50.5 s: 363.5 s in all, against the Go
  packages' cases of the same tests inside `internal/intent`'s, `internal/server`'s and
  `internal/cli`'s runs. Afterwards `Branch` lists `main` and `fylgja-fixture` alone, and
  `FylgjaProbe`, `CoreProposedChange` and `FylgjaStage` count 0.

### 5.15 Tier 2, the stages' ported tests and the compare with the Go reader (T021, Run 19, 2026-10-30)

- **The plan, made of the two halves.** `stage plan` is the orchestrator's flow (T025), so
  the Go tests' `planOf` is ported as `conftest.plan_of`: the proposed change found
  (`stages.find`), each stage in order resolved (`resolve_from`, steps 4–9), read at its at
  and taken by the adapter (`read.read_snapshot`, the take written under the test's
  directory), and compiled by a core server of the test's own (`twin compile --snapshot`, no
  `INFRAHUB_*`), the first rejection ending each stage; then each two consecutive compiled
  stages diffed by the core's `twin diff` (T010), whose `step` block carries what the Go
  plan's steps did (nodes changed and why, links, artifacts, `unchanged`). Each outcome is
  `(label, refused|compiled, the first rejection's rule)`, as Go's `outcomes`. `serving()`
  starts a core server for the session (`core`) or for one test (`own_core`, whose stores
  hold only what the test files), and `Core.state` names its state root.
- **The harness gains** (`conftest.py`): `FixtureTool.propose` (the id), `.mark` (the
  stage's id and its at, written or given), `.update_stage`; `throwaway` collecting the
  branch's proposed changes and their stages before `-delete` and holding none read after
  it, as the Go tests' `testBranch` did; Infrahub's own reads beside the product's
  (`artifacts_of`, `checksums`, `await_moved`, `await_joined`, `artifacts_ready_at`, moved
  from `test_read_fixture.py`, `branch_origin`); `stage_reader`, `stamper`, `resolve`,
  `find`; and `refused`, the Go tests' helper.
- **The fixture tool's new flags** (`cmd/fylgja-fixture/stages.go`), each where a Go test's
  seeding had none: `-set-serial <dev>[,…]=<serial>`, `-describe device:|platform:|
  manufacturer:<name>=<text>` or `virtual:<dev>:<name>=<text>`, `-set-cable-status
  <label>=<status>` (printing the cable's stamp), `-re-end-cable <dev>:<port>=<end>[,…]`,
  `-delete-link <dev>:<port>` (printing when the delete returned), `-add-virtual-interface
  <dev>:<name>`, `-tag-devices <dev>[,…]`, `-rebase`; each refuses `fylgja-fixture`, a branch
  outside `fylgja-test-`, a second of them, any flag beside it but `-branch` and a value not
  of its form, before any request. `-add-device` takes `-device-platform`, `-device-tag`,
  `-device-management` and `-device-group`, each refused without it. Beside the proposal
  flags, `-update-stage <label>:<field>=<value>` (label, as_of or description) and
  `-delete-stages`. `-mixed` now refuses `fylgja-fixture` before any request, where it had
  tried the branch's creation first (`TestSeedMixedRefusesTheFixtureBranch`'s claim).
  `docs/development.md` and the glossary name them.
- **The four files**, each Go test carried over by name:
  - `test_stages.py` (five): `TestStageKindLoads` (the kind on main, the branch's hash
    main's after its load, the mark read, the uniqueness and regex refusals, the stages
    deleted and no orphan); `TestStagesListAndPlan` (the listing's four rows through
    `adapter.stage_list`, the head one microsecond after the latest checksum, the plan's
    outcomes and steps, SC-002's mark read equal to `--branch --at`'s snapshot and bundle,
    the three edits and `twin_moved` on a `RecordView`); `TestStageRefusals` (stale, fresh,
    the serial number cleared by the run-check and the validation read pinned, the rebase,
    `stage.label.reserved`, `stage.at.unresolved`, the unknown label's exact words, the
    close, an unknown branch); `TestStagesSeeEveryWriteOfADevice`;
    `TestStagesSeeARemoval`.
  - `test_stage_take.py` (four): `TestArtifactOnASeededBranch` (its three proofs, the
    bundle's files from the core), `TestMixedSeedReads`, `TestSeedMixedRefusesTheFixtureBranch`,
    `TestPinnedReadReproducesItsBundle` (bundles compared file for file).
  - `test_snapshot_of_a_stage.py` (two): `TestStageTakenTwiceHasOneSnapshot` (the two
    plans' ids equal, the two takes equal but for `observed_at`; the store that keeps the
    first take is the core's, which `twin diff` files into as a step's target does, so the
    second plan's takes keep each first entry's bytes and back-dated mtime, adding none);
    `TestStepTargetFromASnapshot`'s read half (`read --stage --out` through the recording
    proxy names the plan's snapshot with the mark's branch, at and scope; the core then
    builds the target from the file and from the id, to the plan's bundle, with no request
    to Infrahub, after the branch is gone).
  - `test_adapter_matches_go_reader.py` (one): the same arguments to `bin/fylgja intent read`
    through the host's server and to the adapter's `read`: `fylgja-fixture` unpinned and at
    a pinned `at` (`….654321Z`), and a throwaway branch's `seeded`, `third-link` and `head`
    by `--stage` and its branch with `--probes testdata/probes/n1-loop.json`; every file
    byte-equal once its two `observed_at` lines are equalised, the snapshot ids, resolved
    stages and findings equal; then `stage list --json` and `stages --json` equal as JSON.
    The host's server ran T003's build (16 h up, its binary `(deleted)`), whose reader no
    change of this feature has touched.
- **Not carried over**: `stage.main.moved` against a real write, which needs a write on
  main, which no test makes; on this install main holds no tagged device, so the warning is
  never filed (asserted: the listing's findings are none), and its case is tier 1's. The Go
  plan's text lines (`pair.Text()`), logged and not asserted, are T022's.
- **Live, each file run alone, no twin up**, every case green at its first full run (the
  first runs' two failures the harness's own: `serving()` making no root, and a comparison
  marshalling an empty `observed_at`): `test_stages` 1,005.6 s wall (five);
  `test_stage_take` 227.2 s (four); `test_snapshot_of_a_stage` 269.1 s (two);
  `test_adapter_matches_go_reader` 183.8 s (one). 1,685.7 s in all, against
  `internal/stages`' 1,712.9 s in the Go tier. **The read times**, Go's through the host's
  server then the adapter's: the fixture 3.3 s and 2.8 s, pinned 2.1 s and 2.3 s, `seeded`
  14.6 s and 8.7 s, `third-link` 7.5 s and 8.2 s, `head` 6.7 s and 7.1 s, with a probe file
  1.5 s and 1.6 s, the stage list 4.2 s and 3.9 s: 39.8 s and 34.7 s over the seven.
  Afterwards `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`,
  `FylgjaStage`, `FylgjaProbe`, `CoreChangeThread` and `CoreUserValidator` count 0.
- **The gates**: `make build` static; `make test` green (711 Python tests, Go cached) in
  19.1 s wall; `make lint` 0 issues, ruff clean.

### 5.16 The plan, rehearsal and deadline documents, held to the goldens (T022, Run 20, 2026-10-30)

- **The goldens, byte for byte.** `documents/rehearsal.py` renders `tests/golden/rehearsal.json`
  to `rehearsal.md` (the shortened form, 3,506 bytes with `fylgja-cli`), `rehearsal.full.md`
  (the whole form, over the 4,092), `rehearsal.txt` (`stage_lines` then `closing`) and, through
  `findings.Document.text`, `rehearsal.stderr.txt`, each equal but for `fylgja-cli` in the
  reproduce lines (the fenced block, the indented lines, `rehearsal.reproduce`), whole lines
  alone: `step.diverged`'s message, which names the core's `fylgja twin destroy`, keeps it, as
  does the unread run's `fylgja twin show`, the core's command. The markdown takes `plan.json`'s
  `steps` as they are (`Pair.from_dict`). The document re-written equals `rehearsal.json` but for
  the README's one hand edit, `<state-root>`, which the encoder escapes as Go's does. `build`
  re-made from the golden run (each stage's plan findings at resolve, read and compile, the
  step's `push.refused` and `step.diverged` as the child's, the waits, counts, timings and loss
  the core reported) gives the golden block. `documents/plan.py` rebuilds `plan.json` from its
  stages and steps and prints `plan.txt` and `plan.stderr.txt` byte for byte.
- **What the plan's text needs beyond its block**: the proposed change's destination (`→
  main`) and each compiled stage's devices by package (`3 devices (nokia_srlinux 3)`), neither
  in `$defs/plan`, so `PlanResult` carries the destination and `PlanStage` its `packages`, which
  the stage-plan flow (T025) fills from the adapter's read (`packages.py` matches each device).
  A stage's `status` and `rule` are `build`'s `stop` (`PlanStage.stop`): refused under the first
  rejection's rule, failed when it is `operation.failed`.
- **The step between two stages** is the core's `twin.diff` answer between their snapshots
  (T010), whose sides it names `snapshot <8 hex>…`; `pair_of` gives them the stages' references,
  or says which side was refused, as `pairOf` did. The answer's `step` block is the contract's
  (`$defs/step`), whose `artifacts.changed` lists nodes on both sides alone, an artifact that
  came or went with its node "going with the node": the plan's text (`n4 device-config added`)
  and the rehearsal's drawing (`artifacts n2, n4`) name it, so `artifacts_moved` reads it from
  the two compiled bundles' `manifest.json`s, as `step.Diff` lists it (an added node's artifact
  and one a kept node gained; a removed node's and one a kept node lost; a host, which has
  none, never), and `step_of_diff` joins the two. Without the manifests the step renders as the
  contract carries it, those artifacts unnamed.
- **The deadline's budgets (§4's "which file")**: §1.6 had them "in the bundle, no package
  loaded"; they are not. `manifest.json` names each node's package (a device's `psp.id`, a
  host's `probe.package.id`, the format) and no budget; `lab.NodePlans` loads the packages and
  takes `image.deploy_timeout_s`, `image.destroy_timeout_s`, `readiness.timeout_s`, a device's
  `config.push_timeout_s` and a host's `flow.start_timeout_s` and `flow.read_timeout_s`.
  `deadline.node_plans` reads the manifest from `twin.compile`'s files and `load_budgets` the
  packages from the files the core embeds, the shipped `psp/` (or `FYLGJA_PSP_SHIPPED`) then
  `FYLGJA_PSP_DIR`, shadowing by id as `--psp-dir` does, and `probes/`; a node whose package is
  not held is left out, as the host check leaves it. Should `twin.compile`'s document carry the
  budgets instead: **not taken**, since the packages are the repository's own files, which the
  adapter already reads for `platform.matches`, and a core started with a `--psp-dir` the flow
  does not see would mismatch in `platform.matches` before the deadline; the residue, a deadline
  summed from other budgets than the core's server holds, bounds the flow alone, each child's
  activities keeping the core's own timeouts. The mechanism's eleven constants (`MECHANISM`)
  are `provision.DeadlineMechanism`'s, a test holding them to `internal/provision/options.go`
  and `internal/verify/wait.go`, which stay. `go_duration` writes `time.Duration.String` for
  `rehearsal.deadline.unfit`'s message. The golden's 2,580 s comes back from the three-node
  bundle's plans over its baseline and three rehearsed stages.
- **The block's inputs** are the contract's shapes as dicts in the Go structs' key order:
  `Input`, `Stage`, `Result`, `StageResult`, `Provision` and `StepRun` as `report.go` has them,
  a wait as the core reports it with its `failing`, a push and the timings as `twin.step`'s
  block carries them; `Provision` names `fylgja-provision` and `StepRun` `fylgja-step`, the
  core's workflows the flow's `twin.create` and `twin.step` start; the run's own identity is the
  flow's, given in `Result.run` (T026).
- **Carried over by name** (`tests/unit/test_rehearsal.py`, 115; `test_plan.py`, 13;
  `test_deadline.py`, 17): every case of `verdict_test.go` (`TestVerdict`'s sixteen and its
  four phases, `TestNewFindings`, `TestStop`, `TestABurstFailedFailsTheStage`), of
  `report_test.go` (the twelve examples in `tests/unit/rehearsal_examples.py`;
  `TestBlockValidates` against `contracts/findings.schema.json` with `rehearsal.schema.json`
  and `stages.schema.json` by `$id`, `TestBuildRolesAndVerdicts`,
  `TestBuildFilesTheRehearsalsOwnFindings`, `TestBaselineWhoseProvisionDidNotStart`,
  `TestReproduce`, `TestStageLinesAndClosing`, `TestBlockOfARunWhoseEndWasNotRead`,
  `TestFindingsAreTheStagesInOrder`, `TestTheVerifyCellCountsTheBurst`,
  `TestEachStageCarriesItsStepsLoss`), every case of `markdown_test.go` (`TestMarkdown` whole,
  the seventeen others, the sweeps across both shortening boundaries included), and of
  `deadline_test.go`; and `internal/step`'s `TestDiffNodeAdded`, `TestPairTextOrder`,
  `TestPairTextOneLine` and `TestPairJSONSatisfiesTheContract`. `fylgja-cli` in every reproduce
  line, `fylgja twin show` kept. `purity_test.go` has no counterpart beyond a test that the
  three modules import nothing of the adapter, and `check_scope_test.go` and
  `check_timeout_test.go` are the checks', T029's. Every byte length is Go's `len`, in UTF-8
  bytes, `clip` cutting at a character's edge.
- **The lane's venv**: the worktree was seeded without `orchestrator/.venv` (§5.7's dropped
  last path), so the run's Python ran on the main tree's venv with this tree's `src` first on
  `PYTHONPATH`, whose editable install names the main tree, and `make lint` with
  `ORCH_VENV` pointed at it.
- **The gates**: `make build` static; the orchestrator's tier 1 856 passed in 11.5 s (145 new);
  `make lint` 0 issues, ruff clean. No Go changed, so no Go test is this run's.

### 5.17 The five flows: read, schema check, create, step and plan (T025, Run 22, 2026-10-30)

- **The shape.** Each flow is a body, `run(deps, …)`, a plain function of the flow's
  parameters and a `Deps` (the core's client, the orchestrator's store, the adapter's
  environment, how a session is opened, the adapter's `read` and `schema_check`, the out sink,
  the run's id), and a `@flow` of the same parameters that builds the `Deps` from the
  process's environment, runs the body and files the document (`flows/common.py`'s
  `publish`): the run's artifact `fylgja-findings`, key `fylgja-<flow>-<run id>`, `data` the
  document; with no run (a plain call) nothing is filed. Out lines go to a context variable's
  sink (stdout by default, `fylgja-cli`'s when T027 sets one) and to the run's log when a run
  is current. `fylgja_orchestrator.flows` still imports no Prefect; each flow's module does.
- **The adapter's half of a stage**, `adapters/infrahub/session.py`: `Session.open` (the
  packages, a refused one at read; the credentials, unset ones `operation.failed` at resolve;
  the request's one probe list, the file's at start or the kind's at resolve), `find`, `read`
  (a branch read and taken, every finding at read) and `build` (Go's `build`'s Infrahub half:
  resolved with `stage.main.moved` as `MOVED_ALWAYS`, `MOVED_NEVER` or `MOVED_RESOLVED` asks,
  `on_resolved` told so the stage's line prints before the read; then read with an
  `observed_at` of its own and taken, each finding at its step, a failure `operation.failed`
  at its step naming the reference). The create, the step and the plan build every stage
  through it.
- **The core's runs as the flow's document** (`composed`): every run is `detach: true` then
  `run.read` every 2 s (`run_core`), whose last answer is a `run.read` document. The flow's
  document is the create's or the step's as the core's CLI printed it: its operation, the
  flow's subject (`branch`, `at`, `stage`, `scope`) with the run's id, the run's status, the
  flow's findings first (the resolution's and the read's, `step.stage.skipped`,
  `stage.twin.moved`), then the start's but its `run.detached`, then the run's without the
  start's repeats (`withoutRepeats`); the start's blocks, the run's over them, the stage block
  over both. A start the core refused is its own last answer. A dry run is `core.dry_run`,
  never detached.
- **The record follows `twin show`** (`follow_record`): once a create's or a step's run has
  ended, `twin show` is asked once more; when it names the snapshot the flow sent, the record
  is written naming the stage resolved, its proposed change, the snapshot and the flow's run,
  or, for a create from a branch, removed, since that twin names no stage (the record is "the
  twin it last drove", FR-021). A dry run, a refusal, a twin left elsewhere (a diverged step, a
  failed create) or a core that cannot be asked leaves it as it was. Deciding by `twin show`
  rather than by the document's status keeps one rule for every outcome, the trust's own.
- **Departures**, each where the core's words named what the core no longer does:
  - `intent-read`'s summary line is the adapter's (§5.13) with `, stored at <entry>` added
    once the flow files the snapshot under `snapshots/`: no lossy mappings or shared ports,
    the compiler's survey, since a read compiles nothing. Dropped rather than taken from a
    compile, which would cost a request to the core for two numbers.
  - The plan's `read` counts take `lossy_mappings` and `shared_ports` from the compiled
    manifest's `fidelity.lossy`, counted as `Manifest.LossyCounts` counts it, which
    `TestSurveyAgreesWithTheManifest` holds equal to the survey; a stage whose compile the core
    refused has no manifest and counts 0 and 0, where Go's in-process survey counted them.
    The text prints a refused stage's counts nowhere, so only its JSON differs.
  - The snapshot crosses as the store entry's file, under the entry's path, which the core
    files (`twin.create`'s and `twin.step`'s `snapshot`); the document's subject is the
    flow's, not the core's (`snapshot` the path).
  - The create's dry run prints no `read:` line, which the core's dry run of a snapshot has
    none of; the step's stage line prints before the core's `twin:` line, where Go printed it
    after.
  - `twin step`'s `--wait` is the core's to refuse (`verify.wait.invalid` at start), after the
    target's read, where Go refused it before any read.
  - With no scope given, the step reads under the scope `twin show`'s record names, as Go did;
    with none recorded (no twin), under the default, and the core then refuses the host.
  - A stage's build that cannot run names its reference, where Go's create named the
    operation at resolve and `branch <b>` at read; a snapshot's own refusals (the take's) are
    at read, inside the adapter's read, where Go placed them at compile.
- **Tests** (`tests/unit/test_flows.py`, 41): the bodies called plain with the adapter and the
  core stubbed, each stage resolved by the real rules over `test_stages`' reader and stamper
  (`StorySession`, only the branch's read stubbed); each flow's name and parameters
  (data-model §7); `publish` with no run; the composition; the read filed and named, refused,
  and a store that cannot file; the check passed through; the create from a stage (its line,
  the file sent, the document, the record), from a branch (the record removed), a twin left
  elsewhere (kept), its dry run (the core's, no record), four guards before any read, refusals
  at resolution and at read, the core unreachable; the step's default target and record,
  `step.target.required` in its four distrusted cases with nothing read, a given stage under a
  distrusted record, `stage.twin.moved` (US6 scenario 3), `step.target.current`, the twin's
  scope and the flags passed through to its dry run, a diverged step keeping the record; and
  **the plan rendered to the golden byte for byte** (`plan.txt` from the out lines,
  `plan.json` and `plan.stderr.txt` from the document), its compiles and diffs the stubbed
  core's in the golden's order, a refused compile going on, the plan through the story, and
  `build`'s three moved modes. `prefect_test_harness` is not used: the plain bodies keep
  `make test` in budget, Prefect's import adding about 2.5 s once.
- **Live, read-only, no twin**: `schema-check` run as a flow on an ephemeral server
  (`PREFECT_HOME` in the session's scratch, no `PREFECT_API_URL`): the first start in a fresh
  home timed out at Prefect 3.8.8's default `PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS`
  of 20; with 180 the server answered in about 10 s and the run completed in 20.6 s wall, its
  two lines on stdout and in the run's log, its artifact `fylgja-schema-check-<run id>` of type
  `fylgja-findings` with `data` a JSON string (§1.4 again on 3.8.8). T028 and tier 3's
  ephemeral runs need the bound raised. Then the create's, step's and plan's bodies through a
  throwaway core server built from this tree (`127.0.0.1:7698`, a scratch state root, a token
  made for it, no node logins), stopped and removed after: `twin-create --branch
  fylgja-fixture --dry-run` filed snapshot `0940db93…` and the core named bundle `c3872f5c…`
  (SC-002) in 8.8 s, refused at the host check only for the logins the throwaway server
  lacked (`host.probe.login_unset`); `twin-step` with no record, `step.target.required`;
  `stage-plan --branch fylgja-fixture`, `stage.unknown`, no block. The host's own server and
  worker were not touched.
- **The gates**: `make build` static; `make test` green, 951 Python tests in 14.1 s (41 new),
  73.7 s wall uncached at a load of 1.9–4.2, `internal/cli` 41.6 s of it; `make lint` 0
  issues, ruff clean.

### 5.18 The rehearse flow (T026, Run 23, 2026-10-30)

- **The shape.** `flows/twin_rehearse.py`: the body `rehearse(deps, branch, scope, probes_path)`
  returns a `Rehearsed` (the document, its markdown, and the timeout or cancellation that
  reached the run); `run(deps, …, markdown)` sends the markdown to the `MARKDOWN` sink (the out
  sink when unset, `fylgja-cli --markdown`'s stdout once T027 sets it), files the document as
  the run's artifact, then raises what reached the run, so the platform records it after the
  document is filed; `@flow(name="twin-rehearse", timeout_seconds=4020)`. `Deps` gains
  `flow_run` (`record.read_flow_run`), `post`, `budgets` (`deadline.load_budgets`), `now` and
  `clock`. The plan is `stage_plan.plan(deps, op, …)`, `stage plan`'s body factored out
  (`Planned`: the scope, the subject, the session, when resolution began, the result and each
  compiled stage's file, manifest, snapshot id and resolution), printing nothing for a
  rehearsal; `stage-plan`'s golden still renders byte for byte.
- **Over the core's operations.** The baseline rule, `refusalStatus`, the deadline from each
  compiled manifest's packages (§5.16), `rehearsal.deadline.unfit`, then the host: `twin.show`'s
  `in_flight` (a provision, step, destroy or rehearsal run refuses, `run.in_flight` in
  `InFlightRefusal`'s words); the reclaim (below); and the core's dry run of the baseline's
  `twin.create`, its host check, whose refusal is the rehearsal's (its findings without the
  plan's repeats), status error when it could not run. Then the run: the baseline by
  `twin.create` of its snapshot file, detached and read every 2 s, then `twin.verify --wait
  2m0s` (verify's default budget, `MECHANISM.wait`), the wait's failing assertions the verify
  document's rejections; each rehearsed stage by `twin.step` of its snapshot file with
  `allow_restart`, whose block's `wait`, `wait_counts`, `loss`, `pushed`, `timings` and
  `reconcile` (restarted, recreated, added) are the stage's; `rehearsal.classify` against the
  baseline findings; the stop at the first stage `rehearsal.stop` stops at; and the destroy in
  a `finally`, unless the baseline's create could not start because a run holds its id. A
  child's outcome comes from its run's document: `run.cancelled` first, then the step block's
  `outcome`, then the status (ok ready, failed, rejected, else error); the step it stopped at
  is its first rejection's. A child the core refuses at its start carries the core's refusal as
  its stage's findings ("its step did not run"); one whose end cannot be read is
  `operation.failed` on its run unless cut. The record follows the twin after each create and
  step (`follow_record`, flow `twin-rehearse`, this run's id) and is removed after a clean
  destroy when it is this run's, so a run that dies leaves a twin its own record names.
- **The reclaim** (T024's rule): a twin standing whose snapshot the record names, the record's
  flow `twin-rehearse` and its flow run read from the platform `FAILED`, `CRASHED`, `CANCELLED`
  or `404`, is destroyed before the dry run, `rehearsal.twin.reclaimed` (warning, at destroy,
  the dead run's id, 015's words naming the destroy run and what it removed) and the block's
  `reclaimed`; a destroy that leaves something refuses the rehearsal unclean. No record, a
  record of another flow, one `twin show` does not trust, one naming no flow run (a rehearsal
  run with no platform), a run alive or `COMPLETED`, and a platform that cannot be asked all
  leave the twin to the host check, which refuses it `host.twin.present`.
- **The deadline is the flow's clock, not `timeout_seconds`** (T026 says "`timeout_seconds` the
  deadline"): the deadline is known only once the plan has compiled every stage, and a flow's
  `timeout_seconds` is fixed when its run starts; Prefect delivers a sync flow's timeout as an
  exception between blocking calls (§1.5's 11.3 s for a 3 s timeout), so it cannot interrupt a
  child gracefully. The flow keeps the deadline on its monotonic clock from the run's start, as
  the workflow's timer was: `Core.read` gains `stop`, asked before each 2 s wait; once the
  deadline has passed the child in progress is interrupted (`run.interrupt`) and read on to its
  end, the stage is error, the run cut, `rehearsal.deadline.cut`, and the destroy follows,
  never cut itself. `timeout_seconds` is 4,020 s, `fylgja-twin`'s `ALLOWANCE_S` 300, the ceiling
  3,600 and its `DESTROY_S` 120: what its timeout less its 240 s margin covers. A timeout
  reaching the body (`TimeoutError`) is the cut of the stage in progress, a cancellation
  (Prefect's `TerminationSignal`, a `BaseException`, or `KeyboardInterrupt`) its cancellation,
  `run.cancelled`; both destroy and report in the `finally`, and are raised once the document
  is filed. A fault of the flow's own is `operation.failed` at the stage, status error.
- **§4's grace question, measured.** A throwaway Prefect 3.8.8 server on `127.0.0.1:4299`
  (`PREFECT_HOME` in the session's scratch, up in 32 s), a runner serving a flow whose
  `finally` slept 60 s, cancelled by `set_state CANCELLING` with `force`: the `finally` began
  0.09 s after the request, the run read `CANCELLED` within 31 s of it, and the 60 s never
  ended: the runner sends SIGTERM, turned into `TerminationSignal` in the flow, then SIGKILL 30
  s on. The 30 s is fixed in Prefect's source (`runner/_cancellation_manager.py:102`,
  `runner/runner.py:1275`, `grace_seconds = 30.0`) and read from no setting, so **no setting is
  changed**. It does not reach the twin: the destroy is a run of the core's, started detached
  within one request of the cancellation, which the core's worker ends whatever becomes of
  the flow's process, cancelling the child in flight first. What it can cut is the flow's read
  of it, the report and the post, so after a cancellation the destroy is read for 20 s
  (`CANCEL_READ_S`), one still running then reported under `cleanup.incomplete` as going on in
  the core (status unclean), and the post makes no call 27 s after the cancellation
  (`CANCEL_POST_S`). A timeout is not the runner's: the process lives, and the destroy is read
  whole. The server and runner were stopped after. **§1.5's timeout half, on 3.8.8**: a flow
  of `timeout_seconds=3` sleeping in 1 s steps, as a core read polls, on an ephemeral server
  (startup about 31 s at the 180 s bound) got `prefect.flow_engine.FlowRunTimeoutError`, a
  `TimeoutError`, inside the body 3 s after it began, between two sleeps; its `finally` ran and
  the run ended `TimedOut`, type `FAILED`. §1.3's cancel (`set_state CANCELLING` answering
  `ACCEPT`, the run `CANCELLED`) held on 3.8.8 too.
- **The report and its post.** The block, the text and the markdown are T022's renderers,
  the stages listed again after the run (`Session.stage_list`) for `rehearsal.stage.moved` and
  `rehearsal.change.closed`; the block's `run` is `fylgja-rehearse` with the flow run's id,
  the contract's enum unmoved, minted (`uuid4`) when the body runs with no platform. The
  markdown is posted by `adapters/infrahub/comment.py` (`post_comment`, the check's code made
  synchronous over the adapter's SDK client: a `CoreChangeThread` labelled `Conversation`, then
  its `CoreThreadComment`, on `main`, the empty thread deleted when the comment fails, no call
  once `by` has passed), `rehearsal.report.unposted` (warning, the proposed change's id) when
  it fails, the status kept. `infrahub/checks/fylgja_api.py`'s `post_comment` stays until T029
  rewrites `fylgja-twin`, its one caller.
- **Departures**, each where the Go server's words named what the orchestrator does not do:
  - A refusal because the host is held (every rejection but the passed-over branch point's of
    `run.in_flight`, `host.lab.present`, `host.twin.present`) is **not posted**: `fylgja-twin`
    asks again every 30 s while the host is held, and 015's check posted only its last answer;
    a flow that posted each would leave a thread per ask. Every other report is posted,
    refusals before any run included; nothing is posted before a proposed change is found.
  - `run.cancelled`'s message says "by the operator's interrupt or the platform's
    cancellation", since a `twin destroy` no longer cancels a rehearsal, which is no run of the
    core's.
  - The text prints `run fylgja-rehearse <flow run id>` and each child's run line, and not the
    snapshot and bundle lines a create's or a step's start prints, which the plan printed;
    a destroy's start lines are printed.
  - A rehearsal refused before its proposed change is found renders the markdown of no block
    and posts nothing.
- **Tests** (`tests/unit/test_rehearse.py`, 71): the flow's name, parameters and timeout; **the
  golden rehearsal replayed** from `plan.json`'s stages and `rehearsal.json`'s run as the core's
  answers: the document byte for byte but for `fylgja-cli` and each stage's `took_s`, the
  markdown posted and `rehearsal.out.txt` whole as printed, the deadline 2,580 s from the
  packages; `workflow_rehearse_test.go`'s cases by name (every stage passes, stops at a failed
  stage, new finding fails, baseline findings fail nothing, baseline not built, baseline ended
  otherwise is error ×3, step rejected, wait incomplete ×3, the deadline cutting a step, never
  the destroy, a step that finished anyway, the baseline, a wait, cancelled destroys ×3, destroy
  unclean, one stage, child refused, baseline held touches nothing, destroy not started ×2,
  child and destroy closed without a result, a cut child closed without a result); the
  server's pure ones (the guards, the baseline rule, `refusalStatus`, a stale mark refused
  before any run, over the ceiling, R-08's status table, the stages read again); the host (a
  run in flight, not posted), the reclaim's four cases (a dead run ×3, past retention, not dead
  ×5, a twin not the record's ×4) and an unclean reclaim; the record following the run; the
  timeout as the cut; the grace's bounded read and post; the unposted report; the markdown
  sink; and `post_comment`'s thread, empty-thread delete, bound and unset credentials.
- **The gates**: `make build` static; `make test` green, 1,022 Python tests in 17.0 s (71 new),
  80.1 s wall uncached at a load of 1.7–2.2, `internal/cli` 42.8 s of it; `make lint` 0 issues,
  ruff clean. No tier-2 test is this task's (T028's); no twin, worker or server was touched.

### 5.19 `fylgja-cli` and the runner (T027, Run 24, 2026-10-30)

- **The shape.** `cli.py`: argparse, noun-verb, the seven commands of FR-020 with T027's
  flags, `--json` on the root and on every command (cobra's persistent flag), `--version`.
  Each command's flags are its flow's parameters (data-model §7), a flag not given `None`
  and an empty one given `""`, which the flows refuse as the core's server did. The six
  flow functions run in this process (R-08): on the platform `PREFECT_API_URL` names, asked
  first with `GET /version` under `PREFECT_API_AUTH_STRING` (`record.check_platform`;
  `/health` answers without the credential, §1.2), else on Prefect's ephemeral server under
  `PREFECT_HOME` (R-16). `stage list` runs no flow, since R-08 names six: it is a plain body,
  `flows/stage_list.py`, recorded nowhere and asking no platform. What is printed is the
  core's CLI's: the out lines on stdout as they arrive through `common.OUT`, then the
  document's text on stderr, or under `--json` the document alone on stdout (the out lines
  dropped, as a `render: json` answer carried none), or under `--markdown` the report on
  stdout through the rehearse flow's `MARKDOWN` sink and the out lines and the findings on
  stderr; the exit is the document's status's. `common.FILED`, a list `publish` also hands
  each document to, lets the command print the rehearse flow's document after the timeout
  or cancellation it raises once the document is filed.
- **Prefect's two settings, given defaults before Prefect is imported** (`cli.prepare`, only
  in the console script's own process, kept when the environment sets them):
  `PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL=CRITICAL`, since `prefect.flow_runs` propagates to
  the root logger's console handler (Prefect 3.8.8's `logging.yml`), which would print every
  out line again on stderr, the run's log carrying them (§5.17); and
  `PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS=180` (§5.17's 20 s lapse).
- **The runner**, `serve.py`: `fylgja-orchestrator serve` refuses with no `PREFECT_API_URL`
  (a runner on an ephemeral server serves no one) and with a platform that does not answer
  its credential, each a line on stderr and exit 2; then the six flows' deployments `main`,
  its start-up line `fylgja-orchestrator: serving intent-read/main, twin-create/main,
  twin-step/main, stage-plan/main, twin-rehearse/main, schema-check/main on the platform at
  <PREFECT_API_URL>`, never the credential, and Prefect's `serve` with its starting table
  off. **Two facts found live**: `to_deployment`'s default entrypoint is the module's file
  path, which the runner loads as a script, so the first run started through the deployment
  `CRASHED` in 7 s with `ScriptError: … ImportError('attempted relative import beyond
  top-level package')`; each deployment's entrypoint is now its module path
  (`EntrypointType.MODULE_PATH`, `fylgja_orchestrator.flows.schema_check.schema_check`), and
  the same run then `COMPLETED` 7 s after `create_flow_run`, its artifact
  `fylgja-schema-check-<run id>` of type `fylgja-findings`. And `serve`'s default
  `pause_on_shutdown` pauses every deployment as the runner stops, which held a runner whose
  platform had already stopped until SIGKILL; the deployments carry no schedule, so it is
  off.
- **Departures**, each where the core's CLI did what the orchestrator does not:
  - `stage list` reads the record first and asks `twin show` only when there is one, after the
    guards (`--branch`'s form, the scope), as the core refused them before any dial; trusted,
    the record's stage marks its row; distrusted, `record.twin.stale` is the document's first
    finding and no row is marked; a core that cannot be asked is the command's own failure
    (`api.unreachable`, exit 2), as `twin step`'s is (§5.17).
  - The record carries no at's source (T024's note), so `list_stages` takes a mark's from the
    listing (`stages.py`): without it the twin's row in `stages-with-twin.json` had no
    `at_source`. A record naming a mark since deleted still has none.
  - A flow that ends with no document (Prefect's own failure, an ephemeral server that does not
    start, an interrupt) is `operation.failed` naming the flow and saying that any run of the
    core's it started goes on and `fylgja twin show` names it: every run is detached (R-08),
    so the core's CLI's first interrupt, which cancelled the run, has no counterpart here.
  - A flag a command does not know is the command's own document (`operation.failed`, exit 2),
    under `--json` its JSON, as cobra's `unknown flag` was; an unknown noun or verb is a line on
    stderr, exit 2; a noun alone, or nothing, prints its help, exit 0, as a cobra command with
    no run of its own did. `--markdown` beside `--json` is refused as cobra's flag group was,
    worded here.
  - `twin create` takes no `--at`, as T027's line and the flow's parameters have it.
- **Live, read-only, no twin, nothing of the host's touched**: `fylgja-cli schema check
  --branch fylgja-fixture` with no `PREFECT_API_URL` and `PREFECT_HOME` in the session's
  scratch: 40.4 s on a fresh home (the ephemeral server's first start), 16.8 s warm, exit 0,
  the two lines on stdout and nothing on stderr; under `--json` the document alone; both
  runs `COMPLETED` in the home's database with their artifacts. A throwaway platform
  (`prefect server start --host 127.0.0.1 --port 4298`, basic auth made for it, up in about
  32 s): a wrong credential `platform.unreachable … answered 401 Unauthorized`, a closed port
  `… did not answer: [Errno 111] Connection refused`, each exit 2 before any flow; the right
  one 7.5 s, exit 0, no credential in either stream. The runner on it as above. Then
  `fylgja-cli twin create --branch fylgja-fixture --dry-run` on that platform through a
  throwaway core built from this tree (`127.0.0.1:7698`, a scratch state root, a token made
  for it, no node logins): 8.0 s, snapshot `0940db93…` and bundle `c3872f5c…` (SC-002),
  refused at the host check only for the logins the throwaway core lacks
  (`host.probe.login_unset`, exit 1), the snapshot filed under the orchestrator's scratch
  root and no record written. All three processes stopped after, ports free.
- **Tests** (`tests/unit/test_cli.py`, 53): each command's flags as its flow's parameters
  (11 cases) with the flows stubbed, an empty flag sent as given, `--json` on the root or the
  command, every command's runner the flow of its name; text, `--json` and `--markdown`
  streams, the exit of each of the seven statuses, `--markdown` beside `--json`, a document
  filed before the flow raised, a flow ending with none (an error, an interrupt), the sinks
  put back; an unknown command, a command's flag refused (text and JSON, valid under the
  contract), the help; the platform unreachable before any flow, `stage list` asking none,
  `check_platform`'s request, its 401 and no platform; `prepare`; `stage list`'s twin row
  from a record naming no at's source, `stages-with-twin.json` and `.txt` byte for byte, a
  distrusted record (`record.twin.stale`, the listing `stages.json`'s), no record asking no
  core, the core unreachable, the guards before a corrupt record; the runner's refusals, its
  six deployments by module path and its start-up line.
- **The gates**: `make build` static; `make lint` 0 issues, ruff clean; `make test` green,
  1,075 Python tests (53 new), 79.7 s wall uncached at a load of 2.0–3.2, `internal/cli`
  42.8 s of it. No tier-2 test is this task's (T028's); the host's worker and server were not
  touched, and Infrahub only read. `contracts/orchestrator.md`'s text is T036's, the C4 redraw
  and `docs/development.md`'s T037's.

### 5.20 Tier 2, the flows (T028, Run 25, 2026-10-30)

- **The harness** (`orchestrator/tests/contract/conftest.py`). `platform`, a session fixture:
  `prefect_test_harness` with a 180 s start-up bound, under a `PREFECT_HOME` of the
  session's own, skipping without Infrahub itself (a session fixture sets up before the
  autouse skip). **§4's first item, for the harness**: a flow called in this process with no
  `PREFECT_API_URL` is a run the harness records, `COMPLETED`, its document the run's
  artifact `fylgja-findings`, read back through Prefect's client equal to the document the
  call returned; the harness's first start in a fresh home took 26.9–28.3 s in five starts,
  under its 30 s default but close to it, hence 180, `fylgja-cli`'s ephemeral bound. Each test
  points the process at a core server of its own (`use_core`: `FYLGJA_API_ADDRESS` and
  `_TOKEN`, an orchestrator root under the test's directory, the fixture's scope, no
  platform); `serving()` now asserts the core's environment holds no `INFRAHUB_*` and takes
  extra variables; the core reaches the host's Temporal dev server on `:7233`, its default,
  for `twin.show`'s runs in flight. `Flows.run` keeps a flow's out lines and its markdown sink;
  `Core.operations()` reads the core's log, one line a request, as `(operation, outcome)`, so
  a test says what the core was asked. Infrahub's own reads beside: `threads_of`,
  `check_definitions`, `user_validators` and `await_user_checks` (Go's `AwaitUserChecks`).
- **The four files**, each run alone:
  - `test_flows_create_from_fixture.py`: `twin-create --branch fylgja-fixture --dry-run`
    files snapshot `0940db93…` under the orchestrator's root and no record; the core, asked
    one `twin.create`, compiles bundle `c3872f5c…` (SC-002) and refuses the host for the
    SR Linux logins it lacks alone; no twin directory.
  - `test_rehearse_refused_on_a_stale_mark.py` (Go's `TestRehearseRefusesBeforeAnyRun`):
    rejected, exit 1, `stage.artifact.stale` on n1, n2 and n3 first, the block's stages the
    branch point, `seeded`, `description-stale` (refused, the three devices) and the head, no
    run, destroy or baseline, the text's `…/description-stale: refused (stage.artifact.stale)`;
    the core asked `twin.compile` alone; the report posted as the proposed change's one thread,
    its comment the markdown whole (the sink, a printed line, drops its last newline).
  - `test_stage_plan_of_a_throwaway_change.py`: the golden's composition (§5.1): `seeded`,
    `-add-link` and `third-link`, `-add-interface n1:ethernet-1/99` and `-generate` and
    `bad-port`. The plan block's steps equal `bin/fylgja stage plan --json`'s through the
    host's server whole (SC-006), the status and exit equal, and each stage equal but for the
    `read`'s lossy two (§5.17) and the departure below; the core asked `twin.compile` and
    `twin.diff` alone. The host's address and token are taken by a fixture before the test
    points the process at its own core. The comparison goes at T035.
  - `test_rehearse_composed_by_the_fixture_tool.py` (Go's `TestRehearseComposedByTheFixtureTool`):
    each flag's line as Go asserted it (`-propose`, `-ready`, `-add-interface`, `-generate`,
    `-delete`'s `deleted 0 stages, 1 proposed change, branch …`), the port read active,
    uncabled and not management, n1's checksum alone moved. **The task's three, as read
    here**: no flow refuses a draft as such (the check skips one, T029's), so **the draft's
    refusal** is its rehearsal through a core with no login, refused before any run at the
    host check (`host.probe.login_unset`), the head the one compiled stage, not reached,
    `rehearsal.steps.none` warned, the core asked `twin.compile`, `twin.show` and a rejected
    `twin.create` dry run, and the report posted; **the ready change's plan** is `stage-plan`
    once the creation's user checks have concluded (14 s, both `success`) and `-ready` and the
    port are written: the head compiled with `artifact.interface.unrepresented` on
    `n1:ethernet-1/99` naming `omit.interface.unmappable`, where Go asked `intent.read` and
    `twin.compile`; and **the host held**, which no twin or run of the core's may do in
    tier 2, is a twin directory under a second core's state root (the host check's
    `TwinDirPresent`), the four logins' names set to a placeholder, since the host check reads
    only that they are, so `host.twin.present` is the one rejection beside the passed-over
    branch point: refused, and not posted, the thread count still one. `-run-checks user` is
    not run where main holds a check definition, as Go's; on this host it holds `fylgja-step`
    and `fylgja-twin`. The thread goes with the proposed change.
- **A defect, found live and fixed**: `Core.compile` sent `out` only when given, and the core
  refuses a compile without one (`--out is required`, `operation.failed` at compile), so every
  stage a plan or a rehearsal compiled failed, and the rehearsal ended `error`: the flows'
  unit tests stub the core, and §5.17's and §5.19's live plans reached no compile (the
  fixture's `stage.unknown`). `out` is now always sent, `COMPILE_OUT = "bundle"`, a name the
  core echoes in its subject and a line, the bundle's files answering under their own paths;
  `test_core.py` holds the argument.
- **A departure, found live and recorded, nothing changed**: the Go reader ran the package's
  rules at read as well (`stage.Read`'s `validate.Validate` with the registry), so a port the
  mapping omits was warned `artifact.interface.unrepresented` at read and again at compile;
  the adapter's read ends at the intrinsic rules (§5.11, T017), the package's being the
  core's, so the flow's plan and rehearsal file it once, at compile, beside
  `omit.interface.unmappable`. The goldens `plan.*` carry both lines, which the unit tests
  replay with the read's findings stubbed; a live plan of such a stage prints the compile's
  line alone, as the plan test's comparison allows. Whether SC-007's byte-for-byte reaches a
  live plan of such a stage, which would need the compiler's artifact-name check run by the
  adapter at read, is the operator's to say; T028 takes §5.11 as written.
- **Found and fixed in the harness**: `platform` set up before the autouse skip, so
  `test_layout`'s skip case, which runs the contract directory with no `INFRAHUB_*`, started
  the harness for nothing: 36.0 s of `make test`'s Python, 2.2 s once `platform` skips first.
- **Live, each file alone, no twin up**, at a load of 1.9–3.4: `test_flows_create_from_fixture`
  40.9 s wall (the harness 28.1 s, the flow 4.2–7.2 s); `test_rehearse_refused_on_a_stale_mark`
  170.3 s (seeding 31 s, `-propose` 83 s, the rehearsal 12.1 s);
  `test_stage_plan_of_a_throwaway_change` 197.7 s (seeding 22 s, `-propose` 62 s, the flow's
  plan 16.0 s and the Go handler's 13.0 s through the host's server);
  `test_rehearse_composed_by_the_fixture_tool` 174.6 s (seeding 23 s, the draft's rehearsal
  10.2 s, the held host's 10.2 s): 583.5 s in all. Afterwards `Branch` lists `main` and
  `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage`, `FylgjaProbe`,
  `CoreChangeThread` and `CoreUserValidator` count 0 on `main`. The host's server filed the Go
  plan's snapshots into the host's store, as T021's compare did; its worker was not touched.
- **The gates**: `make build` static; `make test` green, 1,075 Python tests, 79.8 s wall
  uncached at a load of 3.3 (110.4 s before `platform` skipped first, against the 90 s
  budget); `make lint` 0 issues, ruff clean.

### 5.21 The checks as the platform's clients (T029, Run 26, 2026-10-30)

- **The shape.** `infrahub/checks/fylgja_api.py`: `variables()` reads
  `FYLGJA_ORCHESTRATOR_ADDRESS` and `FYLGJA_ORCHESTRATOR_AUTH` (`user:password`, split at its
  first colon, refused naming the variable when it has none or carries a control character);
  `Platform(address, auth)` with `trigger`, `wait`, `document`, `lines` and `cancel`; and
  `run(platform, flow, parameters, deadline, close_by)`, the one call each check makes:
  trigger, wait to the end or the deadline, cancel past it, wait on to `close_by`, then the
  document and the out lines, returned as a `Ran`. A fault before the run exists is the
  check's as 015's were (`Unset`, `Unreachable`, `CredentialRefused`, `NoDeployment`,
  `Unexpected`); one once it exists is `Lost`, the run left going on; a cancellation by
  Infrahub while the run has not ended cancels it with a blocking call and goes on, as 015's
  interrupt did. `findings_text` is WriteText's text of the document's findings (held to
  `Document.text()` over the three goldens), which 015's text frame carried. `post_comment`,
  the `/v1/` paths, the frames and the stream are gone. `fylgja_step.py` and
  `fylgja_twin.py` keep their conclusions, the branch point's excuse, the retry while held
  and the margins (`CLOSE_MARGIN_S` 120, `DEADLINE_MARGIN_S` 240, `timeout` 300 and 4,260
  unmoved); `fylgja-twin` writes nothing. `contracts/checks.md` is written from 015's with the
  new reach; `.infrahub.yml`'s comment says it.
- **Verified live on a throwaway Prefect 3.8.8 platform** (`127.0.0.1:4297`, basic auth made
  for it, `PREFECT_HOME` in the session's scratch, up in 27 s; a runner serving stand-in flows
  that call the orchestrator's own `out_line` and `publish` from this tree; all stopped after):
  - `GET /api/deployments/name/<flow>/main` answers the deployment (`id`) within 4 s of the
    runner's start, `404` for one not served, `401` without the credential;
    `create_flow_run` `201`; `GET /api/flow_runs/<unknown>` `404`.
  - `POST /api/artifacts/filter` with `{"artifacts": {"flow_run_id": {"any_": […]}, "type":
    {"any_": ["fylgja-findings"]}}, "sort": "CREATED_DESC", "limit": 1}` answers the run's
    artifact, `data` the document as a JSON string. §1.4's shorthand, the filter at the top
    level, also answered, but with one artifact on the server it could not show whether it
    filtered at all; the nested form, Prefect's schema's, is the one used.
  - **The run's log**: `POST /api/logs/filter {"logs": {"flow_run_id": {"any_": […]}},
    "sort": "TIMESTAMP_ASC", "limit", "offset"}` answers the run's records with `name`,
    `level`, `message`. Prefect's own lines (`Downloading flow code…`, `Beginning flow run…`,
    `Finished in state Completed()`) and the flow's `get_run_logger()` lines share the name
    `prefect.flow_runs`, so a flow's out lines could not be told apart; a child of the run's
    logger, `get_run_logger().getChild("fylgja")`, reaches the API with the run's id under the
    name `prefect.flow_runs.fylgja`. So `common.out_line` now logs there (`OUT_SUFFIX`), and
    the glue keeps that name's records alone (`OUT_LOGGER`). The records landed about 1 s after
    the run read `COMPLETED`; the glue reads until two reads 1 s apart agree, at most five.
    250 out lines came back whole across two pages of 200.
  - **The cancellation, without `force`**: `set_state CANCELLING` without `force` answers
    `ABORT` (`Run is already in terminal state COMPLETED.`) for an ended run, which stays
    `COMPLETED`; `REJECT` for a scheduled one, which the platform ends `CANCELLED` at once;
    `ACCEPT` for a running one, `CANCELLED` 3.7 s later. **With `force`, an ended `COMPLETED`
    run is moved to `CANCELLING` and left there** (`201 ACCEPT`): T029's text and §1.3 name
    `force`, and the glue sends none, since the check's deadline can pass between the run's end
    and the request. A stand-in run cancelled 20 s in read `CANCELLED: Flow run was cancelled
    successfully.` about 6 s later, its document filed from the flow's `finally` and its 250
    lines read.
  - The glue itself, against it: a run ended and read in 6.4 s from the trigger; a wrong
    credential `refused this check's credential (FYLGJA_ORCHESTRATOR_AUTH)`, a closed port
    `cannot be reached: All connection attempts failed`, neither carrying the credential.
- **Departures**, each beside T029's text:
  - `lines(flow_run_id)` beside the four the task names, so that the message keeps 015's
    plan and rehearsal text (FR-024: "with 015's conclusions and messages"), which the
    document does not carry, and `common.out_line` logs under the child above for it.
  - `cancel` sends no `force` (above).
  - The message begins with the run's identity, `flow run <id> of <flow>/main: <state>`, so
    the operator finds the run on the platform.
  - `fylgja-twin`'s "deadline passed before the run's start" sentence (015's T093) goes: the
    check cannot tell a flow's plan from its run, and a cancelled flow files its document,
    which says what was cut. A run that filed no document (`CRASHED`, or cancelled while
    scheduled) is its own failure, naming the run and its state.
- **The Go precheck** (`internal/checks`' `platformReached`): `docker exec` into each of the
  Compose project's `task-worker`s runs a probe on the worker's Python (httpx): the two
  variables, `GET /api/health` with no credential and `GET
  /api/deployments/name/twin-rehearse/main` with it, printing statuses and never a value but
  the address; anything but `200`/`200` is why the test skips, after the draft's skip is
  proved, as the test skipped for a server it could not reach. It replaces
  `thisTreesServer`, the core's bridge server's binary compared with this tree's: the core
  leaves the bridge (R-18), and the deployment's answer says the runner serves the flows.
- **`internal/rehearsal`'s two source-reading tests** (`TestTheChecksPassNoScopeAndFailAnError`,
  `TestTheTwinCheckOutlastsItsRehearsal`), tier 1 until T035 deletes the package: the first
  reads each check's one `run(platform, FLOW_…, {"branch": self.branch_name}` and the flow's
  name from `fylgja_api.py`; the second is unchanged, its constants kept. The Python test
  holds the twin check's own deadline to the flow's `timeout_seconds` and its budgets to the
  flow's.
- **Tier 2, `TestChecksInsideInfrahub`, live** (twice, 170.3 s and 151.2 s, no twin up): the
  task workers carry 019's `FYLGJA_API_ADDRESS` and not yet the override's new two (T030's
  override, T040's `up -d`), so the precheck said `FYLGJA_ORCHESTRATOR_ADDRESS is not set in
  fylgja-infrahub-task-worker-2's environment`; the tree's checks were imported under the
  test's registration (8–22 s), a branch seeded (23–27 s) and a draft opened (pipeline
  84–88 s); `fylgja-test-twin` skipped the draft, success, triggering nothing, and
  `fylgja-test-step` concluded failure with the new glue's `FYLGJA_ORCHESTRATOR_ADDRESS is not
  set in this task worker's environment: the check cannot reach the orchestrator's platform,
  and nothing was sent`, which says the new modules import and run on the worker's Python
  3.14.7; then the test skipped, saying why and what the operator does. Afterwards `Branch`
  lists `main` and `fylgja-fixture`, `CoreReadOnlyRepository` `fylgja` alone with its two
  check definitions, and `CoreProposedChange` and `CoreChangeThread` count 0. The test whole,
  the plan's text and the flow's posted report through the checks, waits on T039 and T040.
- **Tests** (`orchestrator/tests/unit/test_checks_glue.py`, 59): the glue imported by its path
  alone and naming no Prefect; its names held to the flows' (`ARTIFACT_TYPE`, `OUT_SUFFIX`,
  `stage_plan.FLOW`, `twin_rehearse.FLOW`) and the twin check's deadline and budgets to the
  rehearse flow's (`TIMEOUT_S`, `ALLOWANCE_S`, `DESTROY_S`, the wait after a cancellation over
  `GRACE_S`); the variables; `trigger`'s requests, basic auth, one retry on `503` at either
  request and no third, a deployment not served, a refused credential, nothing answering;
  `wait`'s four ended states, its deadline, a failed read asked again and one last, a run not
  held; `document`'s parse, none filed and data no document; `lines`' logger, pages and
  settling; `cancel`'s body without `force`, its three delivered answers and its failures,
  never raised; `run` ended, cancelled at the deadline and waited on, not ended by `close_by`,
  lost, and cancelled by Infrahub; `findings_text` against the goldens; and both checks over
  a stub platform with the SDK's `InfrahubCheck`: the plan's text and the branch point's
  excuse, a stale mark, an error status, no document, the step's own deadline, no deployment,
  no open change; the draft's skip reading no variable, ok, failed, the retry while held
  logged once, the retry's end, the deadline's cancellation and the document read after it,
  a run not ended, a platform lost, and `holders`.

### 5.22 Tier 3's script through `fylgja-cli` (T031, Run 28, 2026-10-30)

- **The shape.** `scripts/e2e.sh`: a second client function beside `fylgja`, `fylgja_cli`,
  runs `orchestrator/.venv/bin/fylgja-cli` with `PATH`, `HOME`, the API's address and token
  (the script's core), `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`,
  `FYLGJA_ORCHESTRATOR_ROOT=$OUT/orchestrator` and `PREFECT_HOME=$OUT/prefect`, and nothing
  else of the script's environment, so `local/.env`'s `PREFECT_API_URL` never reaches it and
  every flow runs on Prefect's ephemeral server (R-16). Every command that names a branch or
  a stage in cases 1 to 8 is `fylgja_cli`'s: the precondition's and case 3's dry runs, every
  create from a branch or a stage, case 1's refused create, case 5's text dry run with
  `--probes`, `compiled_id`'s `intent read` (`twin compile` stays `fylgja`'s), both plans,
  every list, and cases 7's and 8's steps, with no target or `--stage`, their dry run and
  their refusal included. The script's own core server is started by a subshell that execs
  it with every `INFRAHUB_*`, `FYLGJA_DEFAULT_SCOPE`, `PREFECT_API_AUTH_STRING` and
  `FYLGJA_ORCHESTRATOR_AUTH` unexported, so `$!` is the server; its environment is then read
  by name, and its log, at the end, asserted to name none of the five operations that read
  Infrahub (`no_infrahub_request`) and at least one `twin.create`. Its `default scope:` line
  is no longer asserted; `local/.env`'s `FYLGJA_DEFAULT_SCOPE=tag:fylgja` is, at the start.
- **Case 9's precheck** (R-16): the checks on `main` at this tree's commit, unchanged; then
  from inside each task worker of the Compose project (`docker exec … python -c`, the
  worker's own httpx, as `internal/checks`' `platformReached`), `GET /api/health` and the
  authenticated `GET /api/deployments/name/twin-rehearse/main` both `200`, and
  `POST host.docker.internal:7650/v1/twin/show` answering no status (the core on loopback
  alone, FR-005); the platform from the host at `local/.env`'s `PREFECT_API_URL` with its auth
  string, the deployment's id kept; the runner (`fylgja-orchestrator serve` of this venv
  under `PREFECT_HOME=local/orchestrator/prefect`, as `scripts/bring-up.sh` finds it) started
  after `orchestrator/src`'s last change and reading under `FYLGJA_DEFAULT_SCOPE=tag:fylgja`,
  its `FYLGJA_API_ADDRESS` `127.0.0.1:7650`; and the operator's core there, this tree's
  binary and build, logging to `local/server.log` and holding none of `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`, the log's size kept so that what the
  rehearsals asked of it is read at the end (no Infrahub operation, a `twin.create`).
- **`rehearsal_run`**: the comment's `Run \`fylgja-rehearse <id>\`` is the flow run's id
  (the rehearse flow's `run_id` is the platform's flow run id); `GET /api/flow_runs/<id>` is
  `COMPLETED`, of the deployment `twin-rehearse/main`, its `parameters.branch` the case's;
  its log read as the glue reads it (`POST /api/logs/filter`, pages of 200, the logger
  `prefect.flow_runs.fylgja`), and its `run fylgja-provision|step|destroy <id>` lines name
  the core's runs, a provision and a destroy required, each history fetched for the greps.
  The reproduce block asserts `fylgja-cli` on each of its five lines, as the renderer writes
  them (T022, R-13).
- **The greps**: `$OUT` now holds `$OUT/orchestrator` and `$OUT/prefect`; when case 9 ran,
  `local/server.log`, `local/prefect.log`, `local/orchestrator.log` and the platform's home
  `local/orchestrator/prefect/` are searched for every credential, and the three logs for the
  marker; the platform's auth string is searched as its password (whatever form carries it)
  and as the basic-auth header's base64 of the whole, under both of its names. The marker
  grep leaves out directories named `snapshots` (the orchestrator's store under `$OUT`),
  which hold it by design.
- **Departures**, each forced by what the split removed:
  - **Cases 2 and 4 read `--at T` with `fylgja-cli intent read` and create with `fylgja twin
    create --snapshot`**: `fylgja-cli twin create` takes no `--at` (T027, §5.19) and the
    core's create will lose its `--branch` and `--at` (T033). The twin's record is then
    `source` `snapshot`, its provenance still naming `T` from the envelope, and case 4's
    reproduction is still a second read at `T` giving case 2's snapshot and bundle.
  - **Every create is `source` `snapshot`**: the core is sent the snapshot by the flow too.
  - **Case 5's step by id needs the snapshot in the core's store**, and `intent read` now
    files it in the orchestrator's alone (`twin compile` files nothing): the step to `5b` is
    preceded by `fylgja twin step --snapshot <file> --dry-run`, which files it beside the twin
    (`resolveSnapshot` before the plan), asserted clear and `twin.json` unchanged.
  - **Cases 7 and 8 read the stage from the orchestrator's record** (`$OUT/orchestrator/twin.json`,
    R-09) where they read `twin.json` `11`'s: `twin.json` `12`, `twin show`'s record and the
    step's sides name no stage; the step's document names the target in its `stage` block.
    After case 7's destroy the record is distrusted, and the list after the delete carries
    `record.twin.stale` and no record.
  - **The script's own core holds no `INFRAHUB_*` at all**: `local/.env` carries Compose's
    `INFRAHUB_INITIAL_ADMIN_TOKEN` (the API token's value), `INFRAHUB_INITIAL_AGENT_TOKEN`,
    `INFRAHUB_INITIAL_ADMIN_PASSWORD` and `INFRAHUB_SECURITY_SECRET_KEY`, which a core started
    with only the three names unset still holds, as found live below. The operator's core is
    held to the three names alone, as `scripts/bring-up.sh` (T030) starts it; that its
    environment keeps the Compose secrets is left for the operator (the report's open item).
- **Checked offline**, against `local/e2e-016-t056.outputs` (016's last whole run) and the
  goldens: `no_infrahub_request` refuses that run's `server.log` (`intent.read 4x, stage.list
  6x, stage.plan 4x`); the new reproduce assertion holds on that run's `comments-9b.json` with
  `fylgja twin` made `fylgja-cli twin`, and refuses it as it was; the children's `sed` names
  the golden `rehearsal.out.txt`'s provision, two steps and destroy. `shellcheck
  scripts/e2e.sh scripts/bring-up.sh` clean.
- **Checked live, no twin, nothing of the host's touched** (a throwaway core from this tree in
  the session's scratch, its own token, both logins' published defaults, the host's dev
  server; the script's own functions sourced from it): the core's environment holds no
  `INFRAHUB_*`, scope or auth string once every `INFRAHUB_*` is unexported (with the three
  alone, it held the four Compose secrets); the precondition's dry run through `fylgja_cli`
  `ok`, `clear`, three nodes, snapshot `0940db93…`, bundle `c3872f5c…`, in 39.8 s (the
  ephemeral server's first start in a fresh home); case 5's text dry run with `n1-loop.json`
  on the fixture, 17.1 s, its five `nodes:` lines and both hosts' lines matching and `verdict:
  clear` on stdout, nothing on stderr; `compiled_id`'s read and compile, 18.8 s, `0940db93…`
  and `c3872f5c…`, the snapshot filed under the orchestrator's root; a read `--at` now and the
  core's create dry run from that file, `clear`, the envelope's `at` the given one, the core's
  store holding it; `stage list --branch fylgja-fixture` `ok` with no row and no record, `stage
  plan` exit 1 `stage.unknown`; the core's log `twin.create` 3 and `twin.compile` 1, no Infrahub
  operation; no marker in the ephemeral home (5.3 MB, `prefect.db` and its WAL) nor in the
  outputs outside the snapshot files; no Infrahub token, API token or auth string anywhere.
  Case 9's probe from inside both task workers answered `unset FYLGJA_ORCHESTRATOR_ADDRESS`,
  the workers lacking the override's variables until T040, and the core-reach half answered
  `401`, today's server still listening on the bridge: both are refusals the precheck words.
- **Left for T043** (tier 3 itself): every twin-booting assertion; the step's dry run filing
  `5b`'s snapshot beside a twin; the record's moves in cases 7 and 8; the platform's flow run
  and log reads and the core's runs they name; the checks' messages as the new glue writes
  them (`stage_lines`, `contains("rehearsal ok")`, the 9b failure text); the greps over the
  platform's logs and home; the operator's core log read from its offset; and the wall time,
  which grows by each `fylgja-cli` command's ephemeral start (about 17 s warm, about 30
  commands).

### 5.23 The server's removal (T032, Run 29, 2026-10-30)

- **The server.** `internal/server`'s `rehearse.go`, `stages.go`, `schema.go`, `scope.go`,
  `read.go`, `resolve.go` and `probes.go` are gone with their tests (`rehearse_test.go`,
  `rehearse_contract_test.go`, `schema_test.go`, `scope_test.go`, `read_test.go`,
  `probes_test.go`, `probes_contract_test.go`, `snapshot_contract_test.go`). `handlers.go`'s
  table and `api.Operations` hold eleven operations; `operationArgs` gives `twin.create`
  `dry_run`, `snapshot`, `detach` and `twin.step` `snapshot`, `allow_restart`, `dry_run`,
  `wait`, `detach`; `takesFiles` loses the three that took a probe file; `takesStream` loses
  `twin.rehearse`. `Server` loses `Probes`, `RehearsalCeiling` and `DefaultScope`, `options`
  its `rehearsalCeiling`, `call` its `steps` and the markdown frame (`render` `markdown` is
  still accepted and answered as text). A create builds from `--snapshot` alone, refused
  `--snapshot is required` (operation.failed, exit 2) before its files are looked at; a step
  steps to `--snapshot` alone, `step.target.unknown` (`twin step names its target: give
  --snapshot <id|file>`) when it names none, the id the core keeps for this case (§5.13).
  `snapshot.flags.conflict`'s three callers (`snapshotGuards`, `snapshotConflict`,
  `probesConflict`) are gone; the rule stays in `internal/findings` for T035. Gone with the
  read: `runCreateDryRun`, `readTakeCompile`, `readFunc`, the dry run's `read:` line
  (`readSummary`, `readCounts`), `stageTarget`, `carriesRule`, and `rehearsalHolds`, the
  step's guard against a rehearsal in flight, since nothing in the core starts one now.
  `takeSnapshot` is the tests' (`snapshot_test.go`): the server takes no snapshot, the
  adapter does. A step's override package refused is at `compile` for every target (it was
  at `read` for a stage). `contracts/api.schema.json`: the five operations' `args`, the two
  runs' five arguments, the probe file and `intent.read`'s files frame out of the
  descriptions, `fylgja-rehearse` out of the start frame's enum, a 020 sentence in the
  top description; the findings contract's operation enum is T035's, so
  `TestOperationsAreTheContractsAndTheirPaths` holds `api.Operations` to that enum less the
  five. New `internal/server/gone_test.go`: each lost path `404` with no
  `Fylgja-Api-Versions`, the version's sentence, valid against `$defs/problem`, logged as
  `operation=unknown`, nothing run; each lost argument on `twin.create` and `twin.step`,
  alone, beside a snapshot and with a file, `400` "takes no argument"; the two runs' argument
  sets pinned.
- **`fylgja serve`** reads no `INFRAHUB_*` and no `FYLGJA_DEFAULT_SCOPE`: the default scope's
  check and report line are gone, a malformed value no longer refuses the start, and the
  dial line reads `the workflow service (<address>, namespace <ns>), Docker, containerlab and
  the nodes are dialled when a request needs them`; the "not a loopback address" warning
  stays. `serve_test.go` starts every server with the three unset, and once with them set
  (to a scope 017 refused) to the same report; the answer held open at the interrupt is
  `run.read`'s against a workflow service that never answers (the SDK's 5 s dial bound) where
  it was `schema.check`'s against an Infrahub that never answered.
- **Live, no twin, nothing of the host's processes touched**: a throwaway `bin/fylgja serve
  --listen 127.0.0.1:0` of this tree, its environment `PATH`, `HOME`, a token of its own and
  a scratch state root alone: the report as above; `/v1/twin/rehearse`, `/v1/stage/list`,
  `/v1/stage/plan`, `/v1/intent/read` and `/v1/schema/check` each `404`, no
  `Fylgja-Api-Versions`, the sentence; each of `branch`, `at`, `stage`, `scope`, `probes` on
  `twin.create` and `twin.step` `400` "takes no argument"; a create with no snapshot
  `operation.failed: --snapshot is required`; the log `operation=unknown outcome=not_found`
  five times and `outcome=unreadable` ten.
- **Departures from the task's text**:
  - **`probes.go` went whole**, not its kind's half alone: the file's half served the
    `probes` argument, which the task removes, and left would be dead code.
  - **The CLI's tests moved with the server** (T033 owns the CLI's code): the CLI's tests
    drive the harness's in-process server, so the removal failed 147 of the package's 339.
    The fourteen files T033 lists for deletion whole went now (`intent_test.go`,
    `schema_test.go`, `schema_contract_test.go`, `stage_test.go`, `stage_create_test.go`,
    `stage_list_test.go`, `stage_plan_test.go`, `stage_conformance_test.go`,
    `stage_parity_test.go`, `stages_test.go`, `twin_rehearse_test.go`,
    `twin_rehearse_host_test.go`, `infrahub_test.go`, `probes_contract_test.go`), with
    `create_snapshot_test.go`'s stage and read cases and `credential_test.go`'s
    `TestMissingCredentialSendsNoRequest`. The 58 others were moved onto snapshots rather
    than dropped: the helpers the survivors use are in a new `twins_test.go`
    (`executeTwin`, `decodeRecord`, `validateTwinJSON`, `provisionOnSuite`, `runRoot`,
    `storedBundles`, `snapshotCTM`, `fixtureAt`); a create of the fixture branch's head is
    `useFixtureSnapshot` and `--snapshot headSnapshotID` (the fake's unpinned read's id,
    `0d37e2ec…`, reproduced from the fixture with no `at`, so every id the tests pin stands);
    `twin_step_test.go`'s targets are the four stages' snapshots built from their CTMs
    (`stepLabels`: sealed, linked, again, less, each at its at and observed at
    `2026-10-16T12:30:00.000000Z`), filed by `stepHost` and stepped to by id (`stageID`), the
    expected lines a `target: snapshot <s>… (branch change-1 at …)` line and `snapshot <s>…`
    sides. Removed as the stage's alone: `TestStepBesideARehearsalNamesItBeforeAnyRead`,
    `TestStepTargetErrorsExitTwo`, `TestStepReadsUnderTheRecordsScope`,
    `TestStepToAStageOfAnotherProposedChange`, `TestStepStagelessTwinToAStage`,
    `TestStepFromTheBranchPointToTheHead`, `TestStepTargetCurrentByResolvedReference`,
    `TestStepToAStaleStageIsRefused`, `TestStepSnapshotBesideAStageIsRefused`,
    `TestSnapshotFlagConflicts`, `TestCreateFromAStageTakesItsPinnedRead`,
    `TestRefusedReadStartsNothingAndFilesNothing`, `TestUnreachableInfrahubFailsTheCreateAtRead`,
    `TestCreateDryRunFromAStage`, the refusal tables' stage, scope and read rows, and the
    answer table's five lost operations. `TestStepBackToAnEarlierMark` is
    `TestStepBackToAnEarlierSnapshot`. Left for T033 with the code: the commands and flags
    (and `TestNoCommandTakesTheFollowingFlags`' walk, which expects the five commands beside
    `api.Operations` "until T033"), `executeClient`'s nouns, `probes_test.go`'s and
    `env_test.go`'s client-only flag cases, `credential_test.go`'s remaining read cases, and
    `gone_test.go`'s five commands and five flags. `internal/cli` now 228 top-level tests,
    21.7 s.
- **Left for later tasks, found here**: `snapshot.unknown`'s message still says a snapshot id
  "comes from a create, a dry run, a plan or intent read --out on this server" (pinned by
  tests and `contracts/cli.md`; T036's prose); the worker's `workflow_step.go` refusal still
  names `fylgja twin create --branch, --stage or --snapshot` (T034); `show.go`, `destroy.go`,
  `follow.go` and `verify.go` still read a `fylgja-rehearse` in flight, which goes with the
  worker's rehearsal (T034); `internal/stage`'s `Compile` and `internal/intent`'s counts are
  still the compile's and the twin-show code's (T035); the frozen `018-snapshots` copies are
  read by no server test once `validateM10Document` went, unused with it.
- **Tier 1**: `make build`, `make lint` (golangci-lint 0 issues, ruff clean) and `make test`
  green, 49.95 s wall (the Python half 1,134 passed in 17.8 s, `internal/cli` 21.7 s,
  `internal/server` 3.0 s). No tier 2 is named by T032: every contract test it names is
  deleted, and no contract-tagged test remains in `internal/server`, `internal/cli` or
  `cmd/fylgja`; `go vet -tags contract,fixture,e2e ./...` clean.
