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

- **R-01 The platform is Prefect 3.9.0, pinned, on Python 3.14, with a server of the
  orchestrator's own.** Verified in §1.1-1.5. The server runs `prefect server start
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
