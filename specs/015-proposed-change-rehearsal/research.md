# Research: a proposed change rehearsed on a twin

**Feature**: `015-proposed-change-rehearsal` · **Brief**: [brief.md](brief.md) · **Spec**:
[spec.md](spec.md) · **Written**: 2026-10-17, on the development host (Ubuntu 26.04.1,
Infrahub 1.11.2, Docker 29.8.1), by `plan`, after `specify` and `clarify`.

§1 holds what the plan verified live, each fact with how it was verified and the wall time
(UTC) the answer carries; the raw exchanges are in the session's scratchpad and are not
committed. §2 holds the plan's decisions, R-01…R-22, each with what else was weighed. §3
holds the four decision entries the roadmap names for 015, drafted for the operator. §4
holds what is owed at implement. Every fact of §1 that holds goes into
[verified-facts.md](../../docs/verified-facts.md) at the close, with its date.

The brief's "[Infrahub as read](brief.md#infrahub-as-read)" was read from the source and
verified nowhere; every item of it the build relies on is in §1, verified or corrected.

---

<a id="1-verified"></a>
## 1. Verified at plan (2026-10-17, development host)

Everything was done on throwaway objects and undone: a throwaway `CoreReadOnlyRepository`
`fylgja-plan-probe` served from the lab host, three throwaway `fylgja-test-plan-probe*`
branches with one draft proposed change each, a throwaway `fylgja serve` on a scratch state
root with a token made for the probe. After it, Infrahub reads as it began: `Branch` lists
`main` and `fylgja-fixture`; `CoreProposedChange`, `FylgjaStage`, `CoreChangeComment`,
`CoreUserValidator`, `CoreStandardCheck` and `CoreCheckDefinition` count 0;
`CoreGraphQLQuery` holds `device_config` alone; `CoreReadOnlyRepository` holds `fylgja`
alone; `main`'s schema hash is `e43a1cde…` as before. No twin was booted, no worker or
server of the operator's was touched, and no token was printed.

### 1.1 The Docker bridge, and what a task worker reaches (23:05Z)

- The host's default bridge `docker0` is `172.17.0.1/16`; Infrahub's Compose network
  `fylgja-infrahub_default` is `172.18.0.0/16` with gateway `172.18.0.1`. No
  `/etc/docker/daemon.json`, so `host-gateway` is Docker's default: **it resolves to
  `172.17.0.1`**, the docker0 address, on Docker 29.8.1.
- In a running task worker, `host.docker.internal` does not resolve (`gaierror`) and
  `/etc/hosts` holds the container's own name alone. Its route table is the Compose
  network's (`default via 172.18.0.1`). Its environment holds `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN` and no `FYLGJA_*` variable. It has `git` 2.47.3, Python 3.14.7 and
  `httpx` 0.28.1.
- A throwaway `fylgja serve --listen 172.17.0.1:0` (scratch state root, probe token)
  reported `listening on 172.17.0.1:39289` and the line `172.17.0.1:39289 is not a
  loopback address: the API's token is sent unencrypted on it`.
- **A container on the Compose network with `--add-host=host.docker.internal:host-gateway`
  (Compose's `extra_hosts`) resolves the name to `172.17.0.1` and reaches that server**:
  `POST /v1/twin/show` with the token answered `200`, `Fylgja-Api-Version: 1`,
  `Fylgja-Build: 0.1.0-dev` and the `twin.show` document; without the token `401` with the
  problem body. The live task worker `fylgja-infrahub-task-worker-1` reached the same server
  at the literal address, `200`. The server's log held one line a request and no token.
- Docker's inter-network isolation does not apply: the address is the host's own, reached
  through the gateway, not another bridge's container.

### 1.2 How Infrahub 1.11.2 runs a check (the source in the image, `/source/backend`)

- **The check class.** `infrahub_sdk.checks.InfrahubCheck` (the SDK in the image, editable
  at `/source/python_sdk`): `query` required (`ValueError` without one), `timeout = 60` by
  default, `branch`, `root_directory`, `params`, `client`, and `initializer` with
  `proposed_change_id` defaulting to `""`. `log_error` and `log_info` append entries of
  `{level, message, branch}`; `log_entries` renders them as `-----------------------\nMessage:
  …\nLevel: …\n` blocks; `run()` appends `Check succesfully completed` (sic) on a pass. There
  is no `log_warning`.
- **The run.** `git/tasks.py`'s flow `run_user_check` (name `git-repository-run-user-check`,
  run name `Execute user defined Check '<name>'`) calls
  `repo.execute_python_check.with_options(timeout_seconds=model.timeout)(branch_name,
  location, class_name, client, commit, params)`: **the timeout is a Prefect task timeout,
  the class's `timeout` as imported** (`CoreCheckDefinition.timeout`, read at import; a
  change needs a re-import). `execute_python_check` builds the check with
  `root_directory=<commit worktree>`, `branch=branch_name`, `client`, `params`, and **no
  initializer**, so `proposed_change_id` is always `""`: a check finds its proposed change by
  its source branch. The client is the task worker's own (`get_client()`): address
  `http://infrahub-server:8000`, default branch `main`, timeout 60, holding the token the
  worker's environment carries.
- **The result.** The validator's one `CoreStandardCheck` (`kind: CheckDefinition`, `name`
  the definition's) is **reused across runs**: found among the validator's checks and
  rewritten (`created_at`, `message`, `conclusion`, `severity`), created once when absent.
  `message` is `check_run.log_entries`, `conclusion` `success`/`failure` by `check.passed`,
  `severity` `info`/`critical`. A `CheckError` (the module unloadable, the class missing, an
  exception out of `validate`) is `FATAL Error/n:<message>` (sic), conclusion `failure`.
- **The validator.** One `CoreUserValidator` per (repository, check definition), labelled
  `Check: <name>`, **reused across runs** (`previous_validator`, restarted by
  `start_validator`); `run_checks_and_update_validator` sets it `in_progress`, awaits each
  check's flow, marks the validator `failure` at the first failing one and `completed` with
  `success` otherwise. A check flow that raises leaves the validator where it was: see 1.4.
- **When checks run.** The pipeline (`proposed_change/tasks.py`, `run_proposed_change_pipeline`)
  runs the repository checks for `check_type` `REPOSITORY` and `USER`, and for `ALL` (the
  creation) through the generators flow (`do_repository_checks`). `trigger_user_checks` reads
  **the repository's `checks` on the source branch** (`client.get(…, branch=model.source_branch)`),
  so a definition imported after the branch was created is invisible to that branch (1.5).
  `is_draft` is not read anywhere on this path: the checks run on a draft as on any other.
- **No time limit on a validator is applied.** `config.py` declares
  `MiscellaneousSettings.maximum_validator_execution_time` (default 1800, env
  `INFRAHUB_MISC_MAXIMUM_VALIDATOR_EXECUTION_TIME`, which the published Compose file sets),
  and nothing in the backend reads it. A check's bound is its own `timeout`.
- **The merge rule** (`merge_proposed_change`): every validator but the data validator must
  have conclusion `success`, or the merge fails `Unable to merge proposed change containing
  failing checks`; a validator left `in_progress` with conclusion `unknown` blocks it.
- **The module name** (`git/base.py`, `extract_repo_file_information`): the file's directory
  relative to the repository's root directory (`/opt/infrahub/git/<repository id>`), dots for
  slashes, plus the stem: a check at `infrahub/checks/fylgja_step.py` is imported as
  `commits.<sha>.infrahub.checks.fylgja_step`, with `/opt/infrahub/git/<repository id>` on
  `sys.path`. The top package is `commits`, so this repository's `infrahub/` directory does
  not shadow Infrahub's own `infrahub` package, and a relative import between two files of
  `infrahub/checks/` resolves inside `commits.<sha>.infrahub.checks`.
- **The comment.** `CoreChangeComment` (`core_change_comment`, branch agnostic) inherits
  `CoreComment`, whose one attribute is `text` (TextArea, required), and has the one
  relationship `change` (kind Parent, peer `CoreProposedChange`, cardinality one, required).
  Its GraphQL fields are `id`, `hfid`, `display_label`, `text`, `member_of_groups`,
  `subscriber_of_groups`, `change`: **no `created_at` and no `created_by`**. A comment's
  order and author are therefore the text's to carry, which the report's heading does.
- **The UI** (the frontend source in the image, `/source/frontend/app/src`): a check's
  `message` is shown under an `Accordion` titled `Message` in a `CodeViewer`
  (`entities/diff/ui/checks/check.tsx`): monospace, scrolling, plain text. A comment is
  rendered by `MarkdownRender` (`entities/proposed-changes/ui/conversations/comment.tsx`),
  react-markdown with `remark-gfm` (tables) and `remark-breaks`, and Mermaid blocks through
  `rehype-mermaid` (`inline-svg`, `securityLevel: strict`, an error banner above the raw
  diagram on a failure) in `MarkdownWithMermaid`. Read from the source; not rendered in a
  browser at this plan.

### 1.3 A check inside a task worker, live (23:09Z–23:13Z)

A throwaway repository with `.infrahub.yml` (`queries: fylgja_probe` →
`queries/probe.gql`, `{ Branch { name } }`; three `check_definitions` in one file,
`checks/probe.py`) was served from the lab host over dumb HTTP (`git update-server-info`,
`python3 -m http.server --bind 172.17.0.1`) and registered as
`CoreReadOnlyRepositoryCreate(name: "fylgja-plan-probe", location:
"http://172.17.0.1:38765/probe.git", ref: "main")` at 23:09:10. The task worker's `git
ls-remote` read it. The registration reached `internal_status active`, its commit, the
three `CoreCheckDefinition`s (`fylgja-probe` 120, `fylgja-probe-long` 240,
`fylgja-probe-slow` 5, each `timeout` the class's) and the query `fylgja_probe` beside
`device_config` **21 s** after the create (Prefect: `Check connectivity` 23:09:11, `Adding
read only repository` 23:09:16–39, `Import objects` 23:09:20–39, `Pull latest commit`
23:09:21–44, then `Fetch git repository fylgja-plan-probe on <worker>` for each of the two
task workers, 23:09:39–45).

Then `fylgja-test-plan-probe` was seeded (37 s), `-set-role probe` written (a data-only
change), and `-propose` called at 23:10:44. The pipeline: `Data Integrity` 23:11:01–02,
`Schema Integrity` 23:11:19–23, `Artifact Validator` 23:11:28–43, `Process user defined
checks` 23:11:19, `Evaluating user-defined checks on repository fylgja` (the real
registration, which has none) and `… on repository fylgja-plan-probe` 23:11:23, the three
`Trigger user defined checks` flows 23:11:29, the three `Execute user defined Check` flows
23:11:39. **A data-only proposed change runs every repository's checks at its creation,
draft or not.** The validators were created one after another, the user validators 48 s
after the create. `-propose`'s wait (every validator `completed`, 180 s) failed, since one
never completes (below): `pipeline not concluded within 3m0s (last saw validators Check:
fylgja-probe-slow in_progress)`.

**What the probe check saw and did** (its `log_info`s, read back from its
`CoreStandardCheck.message`, 1,962 characters, every line verbatim):

- `branch_name='fylgja-test-plan-probe' proposed_change_id='' params={}
  root_directory=PosixPath('/opt/infrahub/git/18df73d8-…/commits/5c003f83…')
  name='ProbeCheck'`: the source branch is given, the proposed change's id is not.
- `client address='http://infrahub-server:8000' default_branch='main' timeout=60`.
- `FYLGJA env names=[]; INFRAHUB_API_TOKEN set=True`: nothing of Fylgja's in the
  environment until the override gives it; the worker's own token is there.
- `host.docker.internal -> unresolved (gaierror)`: the name needs the override's
  `extra_hosts` (1.1).
- `data keys=['Branch']`: the registered query's answer, unwrapped.
- `API reached at http://172.17.0.1:44103: 200 version=1 build=0.1.0-dev` and `API without
  token: 401`: **a check inside a task worker reaches a Fylgja server on the Docker bridge
  with the bearer token, and is refused without it.**
- `open proposed changes: [('18df73ee-…', 'fylgja-test-plan-probe', True)]`: found by
  `client.filters(kind="CoreProposedChange", branch="main", source_branch__value=<branch>,
  state__value="open")`, with `is_draft` readable.
- `comment created id=18df73fc-…`: **the task worker's client may create a
  `CoreChangeComment`** (`client.create(kind="CoreChangeComment", branch="main",
  data={"text": …, "change": <id>})` then `save()`); read back under the proposed change's
  `comments` with its markdown (a heading, a GFM table, a Mermaid block, a blank line)
  verbatim.
- A 24-line `log_info` message is stored whole, newlines kept: a long multi-line message
  reaches the check's `message` as written.

`fylgja-probe-long` (`timeout = 240`, sleeps 75 s): completed, success, its validator
`completed` 86 s after it started (23:11:32 → 23:12:58). **A check longer than the SDK's
60 s default runs to completion under its own timeout, and the pipeline waits for it.**

### 1.4 What a timed-out check leaves behind (23:11Z, 23:20Z, 23:30Z, 23:34Z)

`fylgja-probe-slow` (`timeout = 5`, sleeps 20 s): its Prefect flow ended `TimedOut`,
`Flow run failed due to timeout: TaskRunTimeoutError('Scope timed out after 5.0
second(s).')`, its `Trigger user defined checks` flow `Failed` with the same, and **its
validator stayed `in_progress`, conclusion `unknown`, with no `CoreStandardCheck` at all**,
unchanged 23 minutes later and across two re-runs (each re-run restarts the same validator
and leaves it the same way). Nothing in the task workers' Docker logs names it. By the merge
rule (1.2) an `unknown` conclusion blocks the merge, so a timed-out check fails safe, and
reads as running for ever in the proposed-change view.

**A timed-out check cannot act after its timeout by awaiting**: `fylgja-probe-finally`
(`timeout = 5`, `try: await asyncio.sleep(20) except BaseException: await
client.filters(…); await client.create(comment)`) posted nothing; the cancel scope cancels
every `await` after the first. **It can act synchronously**: `fylgja-probe-finally-sync`
(the same, with a blocking `httpx.Client().post(API + "/v1/stage/list", …)` in the handler)
reached the throwaway server, which logged `operation=stage.list outcome=ok duration=1.917s`
at 23:34:20 for a check started at about 23:34:12 and cut at 5 s. So a check that must ask
its run to cancel when Infrahub cuts it sends the interrupt with a blocking call, never an
`await` (R-16).

### 1.5 Re-runs, imports and branches (23:20Z–23:34Z)

- **`is_draft` set to `false` starts nothing** (20 s, no validator moved), as 014 found.
- **`CoreProposedChangeRunCheck(check_type: USER)` re-runs the repository checks alone**:
  the pipeline flow 23:20:22–24, the user checks started 23:20:34–37, `fylgja-probe`
  `completed` at 23:20:41, **20 s after the call**; `fylgja-probe-long` at 23:21:55; no
  artifact validator ran and no checksum moved (`checksum.updated_at` stayed at 23:11:37).
  The same validator nodes restarted (`started_at` moved), `fylgja-probe`'s one check node
  was rewritten in place (`created_at` moved), and the probe posted a **second comment
  beside the first**, which nothing edited.
- **`InfrahubReadOnlyRepositoryImportLastCommit` imports a new commit in seconds** (a
  fourth definition 6 s after the call) and each task worker fetches it in its own flow
  (`Fetch git repository fylgja-plan-probe on <worker id>`, two workers: `3eb89672…`,
  `e705132a…`; both done 13 s after the third import). **A run-check 6 s after an import
  failed on the worker that had not fetched yet**: `Execute proposed changed pipeline`
  `Failed` with `ValueError: SHA b'1ff206a0…' could not be resolved`, `Pull latest commit`
  and that worker's `Import objects` `Failed` with `CommitNotFoundError`, the other
  worker's import `Completed` at 23:23:00, and no validator started. After an import, wait
  for both fetches before a run-check (R-21).
- **A definition imported after a branch's creation never runs on that branch**: the
  fourth check had no validator on the first proposed change's re-run at 23:26:57 (the
  three it knew ran), and ran on a branch created after the import (`fylgja-test-plan-probe2`
  at 23:30:09: `Data Integrity` then four user validators). The branch sees `main`'s
  repository, and its `checks`, as they were at its creation. A branch made before the
  checks land on `main` needs a rebase or a recreation.
- `CoreProposedChangeCreate` by GraphQL on a bare branch (no seed) ran the pipeline the
  same way: `Data Integrity`, then the user validators 20 s after the create.

### 1.6 Deleting under comments and validators; the registration's removal (23:33Z–23:37Z)

- **`CoreProposedChangeDelete` succeeds under three comments and a stuck validator**
  (`ok: true`, no error), and **its comments and validators go with it**:
  `CoreChangeComment` fell from 3 to the other proposed change's 1, `CoreUserValidator`
  and `CoreStandardCheck` to the other's. The comment's `change` is a Parent relationship,
  which cascades, unlike the stage's Attribute relationship, which refuses (014, §8.8). So
  `fylgja-fixture -delete` and `DeleteTestBranch` need no comment step: `deleted 0 stages,
  1 proposed change, branch fylgja-test-plan-probe2` removed the branch's proposed change
  with its comment and validators.
- **`CoreReadOnlyRepositoryDelete` removes the registration's definitions and query**:
  `CoreCheckDefinition` 0, `CoreGraphQLQuery` back to `device_config`, as 10-07 found for
  a `CoreRepository`. The validators and checks hung on the deleted proposed changes, so
  none remained to orphan.

### 1.7 Timings the deadline and the ceiling are set against

From the last tier-3 runs on this host (`local/e2e-014-srl.out`, 2026-10-17, `E2E-PARTIAL`
665.7 s; `local/converge-e2e.out`), SR Linux, three nodes: a create takes 42–56 s (nodes
ready 0.1–0.35 s after the deploy returns); `twin verify` 2.5–4.9 s; a step with one link
added and two pushes 14.2 s, an unchanged step 9.9 s, each with its wait settled inside;
a destroy 2.0–3.4 s; `stage plan` of four stages 5.0–10.3 s; a seed 18–27 s; `-propose`
37–41 s on a seeded branch. The mixed twin's create took 90.6–91.5 s (cEOS ready 9–12 s
after the deploy). A rehearsal of the fixture's three resolving stages is therefore about
a minute and a half of twin time plus the check's overhead, against SC-006's fifteen
minutes.

The budgets the deadline sums (Constitution II): `nokia_srlinux` deploy 180, readiness 60,
push 30, destroy 60, memory 2048 MiB; `arista_eos` deploy 300, readiness 90, push 30,
destroy 60, memory 1536 MiB; the mechanism constants `CheckHostBudget` 30, `StageBudget`
60, `RecordBudget` 30, `PlanTeardownBudget` 30, `UnstageBudget` 30, `ReadinessMargin` 15,
`PushMargin` 15, `VerifyMargin` 30, `InspectTwinBudget` 30; the wait `verify.DefaultBudget`
120. R-09 gives the sums.

### 1.8 What the probe did not verify

- The UI's rendering, in a browser, of the comment's table and Mermaid and of a long
  message: read from the frontend's source alone (1.2). The hand scenarios at implement
  look at both (§4).
- The override's `extra_hosts` and environment applied to the task workers by Compose: the
  mechanism (`--add-host … :host-gateway` on the Compose network) is 1.1's; the override
  itself is applied at implement (§4).
- A push refused for a port the node lacks, this plan's means of a failing stage (R-14):
  the fact is M6's and M7's (`psp/nokia_srlinux.yaml`: the node refuses port 99, "max is
  58"; [architecture §6](../../docs/architecture.md#6-known-limitations), the lossy
  mapping's push refusal), not re-verified here; tier 3 proves it on the rehearsal.

---

<a id="2-decisions"></a>
## 2. The plan's decisions

<a id="r-01"></a>
### R-01 The rehearsal is a fifth workflow, `fylgja-rehearse`, that runs provision, step and destroy as children under their fixed ids

**Decision**: `internal/provision` gains `Rehearse`, a short workflow with the fixed id
`fylgja-rehearse` (Constitution VIII, D-007), registered beside the four. It runs the
baseline's build as a child `fylgja-provision` (already compiled, as a rebuild's child
is), then its wait as the activity `VerifyTwin` on the run's own context, then each later
stage as a child `fylgja-step`, and the destroy as a child `fylgja-destroy` on a
disconnected context, whatever happened; every child under `ChildOptions` as `Reconcile`
runs its two. Its input is everything the server decided (R-02); it reads no disk and no
Infrahub. Its deadline is a workflow timer that cancels the children's context (R-09); the
operator's interrupt cancels the run's. It returns one result in every case, never an
error. **Rationale**: the children keep their own second locks, cleanup paths and histories
(`Provision` cleans up on a disconnected context, `Step` records diverged, `Destroy` is
the cleanup), serialise with the operator's runs by the ids they hold, and `Reconcile` is
the precedent for a run of runs. **Alternatives**: one workflow scheduling the activities
itself (rejected: it would repeat the three workflows' logic and their cleanup, and lose
the locks a step applies at `inspect`); the server driving the runs one by one (rejected:
the server keeps nothing between requests, D-014, and a client gone would end the
rehearsal where D-040 leaves a run running); a signal or a long-running workflow (rejected,
D-007). The entry is §3's D-051.

<a id="r-02"></a>
### R-02 The server resolves and compiles every stage, decides the baseline, the deadline and the host, then starts the run

**Decision**: `twin.rehearse`'s handler, `runRehearse`, does in this order, each refusal
ending the request with its document and nothing started: the flag guards (`--branch`
required and a branch, as `stage plan`'s); the packages; `stages.Plan` over the branch's
open proposed change with the dry run's filing pipeline, as `stage plan` runs it, so every
stage is resolved, read, compiled and filed with 014's refusals and warnings; the
**baseline rule** (R-03); the **deadline** from the compiled stages' node plans (R-09);
the host (R-04: the runs in flight, the reclaim, the host check of the baseline bundle in
this process, as a dry run checks it); the **step chain** (R-05); then the start, the
follow and the report (R-10). A proposed change whose stages all compile but whose
deadline cannot fit the ceiling is refused `rehearsal.deadline.unfit` before the host is
looked at. **Rationale**: FR-001 and FR-003 want every stage decided before a boot, and
`stage plan` already is that; the server is where every refusal is made (XI). The plan's
bundles are filed in the store as a dry run files them, so the run's children read them
by path (D-041's seam).

<a id="r-03"></a>
### R-03 The baseline is the first stage in order that compiled; a branch point refused `contract.node.missing` alone is passed over

**Decision**: walk the plan's stages in order. The branch point refused with exactly one
rejection, `contract.node.missing`, at `read`, is kept as a row (`role: refused`,
`verdict: refused`) and passed over (FR-003, the development host's case, 014's R-04). Any
other stage with a rejection, or a stage that `failed`, refuses the whole rehearsal with
the plan's findings: status `rejected`, exit 1 (or `error`, exit 2, for `operation.failed`
and `intent.at.precision`, as `stage plan` ends). The first compiled stage is the baseline;
the stages after it are rehearsed in order. One compiled stage alone is rehearsed as the
baseline with the warning `rehearsal.steps.none`, and ends `ok` when its verify is clean
(FR-003's last sentence, clarify's answer). **Rationale**: FR-003 names the one exception
and nothing else.

<a id="r-04"></a>
### R-04 The host: runs in flight refuse, a dead rehearsal's twin is reclaimed, anything else refuses as today

**Decision**: before the start, the server asks the workflow service (as `twin step`'s
start asks it) whether `fylgja-rehearse`, `fylgja-provision`, `fylgja-step` or
`fylgja-destroy` is running: any of them is `run.in_flight`, exit 1, naming the run, before
the host is read. Then it inspects the host in its own process. **A twin whose record
carries a `rehearsal` block (R-06) naming a `fylgja-rehearse` run that is not running is
reclaimed**: the server runs the destroy through `StartDestroy` as `twin destroy` does,
its events in the answer under the notice `reclaiming the twin of rehearsal run <id>`,
and the report's `reclaimed` block says what the destroy removed; a destroy that leaves
something refuses the rehearsal with `cleanup.incomplete`. Then the host check of the
baseline bundle runs in this process (`lab.CheckHost` through `dryRunActivities`), with
every refusal it makes today: a lab, a twin directory, an orphan, the memory sum, an unset
login, an absent image, each under its identifier at `host_check`, exit 1. **Rationale**:
FR-007 and VII; no new lock and no waiting in Fylgja (the check retries, R-16). A record
without a rehearsal block, a hand-built twin and an orphan are refused by the host check's
presence refusals as every create is. **Alternative**: reclaiming inside the workflow as a
first child destroy (rejected: the reclaim is a decision about the host's record, which the
server reads today, and a refusal must come before any run).

<a id="r-05"></a>
### R-05 The step chain is computed by the server from the plan; the run reads containerlab's plan itself

**Decision**: for each pair of consecutive compiled stages after the baseline, the server
builds a `provision.StepInput` as `twin step` builds one, except that it reads no twin:
`From` the previous stage's side (`StageRef`, bundle id, `at`), `To` the target's,
`ToBundlePath` the store's copy, `Diff` the plan's `step.Pair`, `Unchanged`, `PushPlan`
from `step.PushPlan(s, step.Lifecycle{})` (the run adds what its own plan restarts,
recreates or creates, `withLifecycle`), `Changed`, `AllowRestart: true` (FR-004),
`Declared` from the registry, `WaitS` `verify.DefaultBudget`'s, and an **empty `Plan`**:
the run reads containerlab's plan at its own step 3, applies the rules as its second locks
and acts on that plan, as it does when the CLI's plan has moved under it. The step's first
lock (`notPlannedFrom`) holds the record to `From`, which the previous child's record wrote.
**Rationale**: there is no twin to read containerlab's plan against before the baseline is
booted, and the step workflow already treats its own plan as the one it acts on.
**Alternative**: a dry run inside the workflow before each step (rejected: it is what step
3 is).

<a id="r-06"></a>
### R-06 The twin record moves to `7`: a `rehearsal` block, or `null`

**Decision**: `twin.json` `7` adds `rehearsal: {"workflow_id": "fylgja-rehearse", "run_id":
…}` or `null`; nothing else moves. `ProvisionInput` gains `Rehearsal *wire.RehearsalRef`,
copied into `RecordInput` and the record as `Stage` is; a step's record keeps the previous
record's. `twin show`'s kind line names it (`pinned at …, stage b/seeded, of rehearsal run
fylgja-rehearse <id>; not following`), its `show.record.rehearsal` carries it, and `twin
verify`'s first line names it too. The `6` schema is frozen under
`internal/lab/testdata/contracts/014-proposed-change-stages/`; a `6` record reads with
`Rehearsal` nil. **Rationale**: FR-008 wants the record to say so with the service down,
and FR-031 allows the move with a frozen copy. **Alternative**: asking the workflow service
whether the record's provision run was a child of a rehearsal (rejected: `twin show` must
say it with the service unreachable, and the record is the twin's provenance, IX).

<a id="r-07"></a>
### R-07 A stage's verdict is computed in the workflow from the child's result and the baseline's wait; the verify's counts ride on the activity's result

**Decision**: the classification is a pure function, `rehearsal.Verdict`, in a new package
`internal/rehearsal` (R-11), called by the workflow after each child: `passed` when the
step ended `stepped` or `unchanged` and its wait's `Failing` holds no `(rule, object)` the
baseline's `Failing` does not hold (`verify.record.holds` is never among them, and a wait
that `settled` holds none); `failed` when the step is diverged (any phase), or when a
finding is new; `error` when the step ended `rejected`, `error` or `cancelled` before its
stage, or its wait is `incomplete` (a node unread, so nothing can be compared), or the
deadline or an interrupt cut it (R-09); `not reached` for every stage after the first that
is not `passed`; `baseline` for the baseline, whose wait's `Failing` are the **baseline
findings**; `refused` for R-03's branch point. The baseline's wait is `VerifyTwin` on the
run's context with `From` the record's `recorded_at` and `BudgetS` the default; its
`RunID` is the rehearsal's, so it writes nothing into the record (`Recorded: false`) and
the result is the rehearsal's own. So that the report carries each stage's verify counts
(FR-012), `wire.VerifyResult` gains `Counts *VerifyCounts` (held, failed, skipped, unread
per kind, the last read's), filled by `VerifyTwin`, and `provision.StepResult` gains
`WaitCounts`, filled by `observeStep`; both omitted when nil, so the three recorded step
histories replay unchanged. **Rationale**: FR-002 compares findings by rule and object;
the wait's `Failing` already carries exactly that, and the step's wait is the verify
(D-039). **The verdict `error` is a sixth beside the spec's five**, needed by the spec's
own edge cases (a step that could not run, the deadline, the interrupt), for `analyze` to
settle in the spec's Key Entities.

<a id="r-08"></a>
### R-08 Status and exit, and the identifiers

**Decision**: `ok` 0 when every rehearsed stage passed; `nonconforming` 5 when a stage
`failed`; `error` 2 when a stage's verdict is `error` (the step could not run or was
rejected by its locks, the wait incomplete, the deadline, an interrupt), after the destroy;
`failed` 3 when the baseline's provision child did not end ready and cleaned up, with the
child's findings; `unclean` 4 when the destroy child's cleanup left something
(`cleanup.incomplete`), whatever the stages did; `rejected` 1 for every refusal before the
start. No new status, step or exit (FR-009). The identifiers, each `rehearsal.*`
(Constitution X):

| Rule | Severity, exit, step | When |
|---|---|---|
| `rehearsal.deadline.unfit` | rejection, 1, `start` | the stages' summed budgets exceed the ceiling; names both |
| `rehearsal.twin.reclaimed` | warning, 0, `destroy` | a dead rehearsal's twin was destroyed before the start; names its run |
| `rehearsal.steps.none` | warning, 0, `resolve` | one stage alone compiled; the baseline was built, verified and destroyed, and no step rehearsed |
| `rehearsal.stage.failed` | rejection, 5 (status `nonconforming`), the phase's step or `observe` | a stage failed: by divergence (naming the phase and the nodes landed and not) or by a finding the baseline did not have (naming it) |
| `rehearsal.stage.error` | rejection, 2, the step reached | a stage's step could not run, was rejected by its locks, was cancelled before its stage, or its wait could not complete |
| `rehearsal.baseline.failed` | rejection, 3, `provision` | the baseline could not be built; the provision child's own findings stand beside it |
| `rehearsal.deadline.cut` | rejection, 2, the step reached | the deadline passed: names the stage, each finished stage's time and the deadline |
| `rehearsal.stage.moved` | warning, 0, `resolve` | after the run, a rehearsed stage no longer resolves to the `(branch, at)` it was rehearsed at, or is gone, the head included |
| `rehearsal.change.closed` | warning, 0, `resolve` | after the run, the proposed change is no longer open |

`run.cancelled` (the operator's interrupt), `run.in_flight`, `host.*`, `cleanup.incomplete`,
`stage.*`, `step.*` and `verify.*` keep their identifiers and meanings; the baseline's and
each stage's verify findings keep verify's, carried in the document's list as **warnings**
whose object is prefixed with the stage (`b/seeded: n1:ethernet-1/2`), since a rejection
would end the document `rejected` and the baseline's fail nothing (FR-002); a new finding
fails its stage through `rehearsal.stage.failed`, which names it. `stage.main.moved` and
the plan's other warnings are carried from the plan.

<a id="r-09"></a>
### R-09 The deadline is the sum of the stages' budgets; the ceiling is 60 minutes, the live check's timeout 70

**Decision**: the deadline, in seconds, is summed by `rehearsal.Deadline` from each
compiled stage's node plan (the host check's `wire.NodePlan`s, read in the server as the
dry run reads them), per node the largest of each budget over the stage's nodes
(Constitution II), plus the mechanism constants:

- the baseline: `CheckHostBudget` + `StageBudget` + deploy + (readiness + `ReadinessMargin`)
  + (push + `PushMargin`) + `RecordBudget`, plus the wait `DefaultBudget` + `VerifyMargin`;
- each later stage: `InspectTwinBudget` + `CheckHostBudget` + `CheckHostBudget` (the plan)
  + `StageBudget` + deploy (the reconcile) + (readiness + margin) + (push + margin) +
  `RecordBudget` + (`DefaultBudget` + `VerifyMargin`);
- the destroy: `PlanTeardownBudget` + destroy + `UnstageBudget`.

For the fixture (three SR Linux nodes, the branch point refused, two marks and the head):
570 + 630 + 630 + 120 = **1,950 s**; with a compiled branch point 2,580 s; the mixed
fixture's three stages 2,400 s. **The ceiling is `rehearsal.Ceiling = 3600 s`**, a
mechanism constant of Fylgja's own, the operator's patience as the wait budget is (D-039;
the spec's assumption): a rehearsal whose deadline exceeds it is refused up front
(`rehearsal.deadline.unfit`, naming the time and the ceiling). **`fylgja-twin`'s
`timeout` is 4,200 s**: the ceiling, the destroy's whole budget (120 s), 300 s for the
work before `start` (the plan, a reclaim, the host check) and a margin of 180 s, so a run
that uses every budget ends before the check's own deadline and the destroy runs inside
the check (FR-006, FR-021); **`fylgja-step`'s is 300 s**
(a plan of the fixture takes 5–10 s). The workflow enforces the deadline with a timer on
the run's own clock that cancels the children's context; a step cut mid-way records
diverged (D-036) and the destroy follows; the report says `rehearsal.deadline.cut`. The
check's own `timeout` matters more than Infrahub's: 1.2's validator limit is unused.
**Alternatives**: a fixed deadline per check (rejected by clarify); the actual timings
(1.7) as the budget (rejected: II says the budgets are the packages', and the deadline bites
only when something hangs).

<a id="r-10"></a>
### R-10 The report: the `rehearsal` block, its text and its markdown; `render: markdown` is a third rendering

**Decision**: the document is `findings_version` `1`, operation `twin.rehearse`, with a
`rehearsal` block under `contracts/rehearsal.schema.json`
([contracts/rehearsal.schema.json](contracts/rehearsal.schema.json)): the proposed change,
`resolved_at`, the deadline and the time used, the reclaim, the run, the baseline's
findings, one entry per stage in order with everything FR-012 names, the destroy's cleanup
and the reproduce commands. The text (FR-013) prints the run's progress as every run does,
each child's lines under a `stage <ref>:` heading the server prints as it sees the child
start (the children come in the input's order), then one line per stage with its verdict,
then the findings as every document prints them. The markdown (FR-014) is rendered from
the block by `internal/rehearsal` (R-11): the heading naming Fylgja, the proposed change,
the run and `resolved_at`; the table; a Mermaid `flowchart LR` with one node per stage and
one edge per step labelled with what the step changed (nodes and links added or removed,
artifacts changed, by name, never a line); the stages as `stage list` prints them; the
warnings; the baseline's findings; on a failure the commands that reproduce it (`twin
create --stage <baseline>`, each `twin step --stage <ref> --allow-restart` to the failed
stage, `twin verify`, `twin destroy`); and the fidelity caveat. The API's `render` gains
`"markdown"`: the `out` and `err` frames as under `"text"`, and the `document` frame
carrying `markdown` beside `text`; an operation with no markdown rendering, asked for
`markdown`, answers as under `text` (no other operation gains one). `twin rehearse
--markdown` prints the markdown alone on stdout and exits by the document; `--markdown`
with `--json` is the client's own refusal, exit 2, nothing sent. **Rationale**: clarify's
answer; a rendering stays outside the document, as the text does. **Alternative**: the
markdown in the block (rejected by clarify).

<a id="r-11"></a>
### R-11 A new package, `internal/rehearsal`, holds the rehearsal's pure rules and renderings

**Decision**: `internal/rehearsal` holds `Deadline` (R-09), `Verdict` (R-07), the
`RehearsalBlock`'s builder from the run's input and result, `Reproduce` (the commands) and
`Markdown` (the rendering), importing `findings`, `lab/wire` and `step` and nothing else of
the module, with no I/O and no clock, held pure by a test in `step`'s shape. The server
imports it for the report and the deadline; `provision` imports it for the verdict (no
cycle: `rehearsal` imports neither). The C4 model gains the component in both the server
and the worker, redrawn in the same change. **Rationale**: the rules are tested at tier 1
without a service, as `step` and `verify` are, and are shared by the workflow and the
server. **Alternatives**: the rules in `provision` (rejected: the server would import
workflow code for a rendering); in `findings` (rejected: `findings` imports nothing of the
module and must stay so for the client's boundary).

<a id="r-12"></a>
### R-12 The API: `twin.rehearse`, its frames and `twin show`'s view of the run

**Decision**: `twin.rehearse` is `POST /v1/twin/rehearse`, argument `branch`, taking an
interrupt from `start`; its frames are a run's (`start` with `workflow_id`
`fylgja-rehearse`, `run`, the `event`s of the run and its children as `Follow` already
reads a check's children, the `document`). `api.schema.json`'s `start.workflow_id` enum
gains `fylgja-rehearse`; `api.Version` stays `1`. `twin.destroy` cancels a rehearsal in
flight first and waits for it, as it waits for a step's record (`StartDestroy` gains the
rehearse step before the provision one); `StartProvision` and `StartStep` refuse while a
rehearsal runs (`run.in_flight` naming it). `InFlight` lists `fylgja-rehearse` with its
child and the step it is at, as it lists a check, and never its child twice; `twin show`'s
kind line says `rehearsal run fylgja-rehearse <id> is at stage <ref>, step <step>` from
the run's input and history. **Rationale**: FR-008, FR-012, the API's shape for a run.

<a id="r-13"></a>
### R-13 The checks: two files and a shared module under `infrahub/checks/`, one query, glue alone

**Decision**: `infrahub/checks/fylgja_step.py` (`class FylgjaStep(InfrahubCheck)`,
`timeout = 300`), `infrahub/checks/fylgja_twin.py` (`class FylgjaTwin`, `timeout = 4200`)
and `infrahub/checks/fylgja_api.py` (the shared glue: the two variables, the request, the
frames, the proposed change by branch, the comment), imported relatively, which 1.2's
module naming allows; one query `infrahub/queries/proposed_change.gql`
(`{ CoreProposedChange(source_branch__value: …) }` is not needed: the class's required
query is `fylgja_branch`, `{ Branch { name } }`, a cheap read the SDK requires and the
checks ignore); `.infrahub.yml` gains the query and two `check_definitions`, `fylgja-step`
and `fylgja-twin`, global. Each check: reads `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`
(`log_error` naming the unset one, nothing sent); finds the open proposed change by
`self.branch_name` with `self.client.filters` (1.3), `log_error` when none; `fylgja-twin`
then reads `is_draft` and, on a draft, `log_info`s that it skipped a draft and returns
(FR-018); sends one `POST` with `httpx` (streaming, no read timeout, `Fylgja-Stream` on
`twin.rehearse`), reads the frames to the document, and maps the document's `status`
alone to its conclusion (FR-022): `fylgja-twin` `ok` → pass, anything else → `log_error`
with the document's text; `fylgja-step` passes unless the plan's findings hold a rejection
other than `contract.node.missing` on the branch point (FR-017), the text as its message
either way. The comment is `fylgja-twin`'s one write (`CoreChangeComment`, `text` the
frame's `markdown`, `change` the proposed change), posted after the document is read, its
failure `log_info`'d without failing the check (FR-019). A transport fault, a `401` or a
`404` under `Fylgja-Api-Versions` is `log_error` naming the address, never the token. The
Python decides nothing else: no verdict, deadline or wording of its own. **Rationale**: the
brief's Decided; the probe's facts (1.3). **Alternatives**: one file for both checks
(rejected: two definitions, two timeouts, two failure rules); the OpsMill skill's
`check_definitions` shape is followed, and its `query` rule (the query on the class).

<a id="r-14"></a>
### R-14 A stage made to fail: an interface the device does not have

**Decision**: tier 3's failing stage and the README's are made by `fylgja-fixture
-add-interface n1:ethernet-1/99`, a new flag writing one uncabled physical interface,
enabled, on a throwaway branch's device, followed by `-generate`: the compile omits it
(`omit.interface.unmappable`, out of the SR Linux rule's range 1–58) and warns
`artifact.interface.unrepresented`, the stage compiles, the step pushes the device's new
artifact, and the node refuses the line (`push.refused`): the step diverges at `push`, the
stage fails, the twin is destroyed, and the report names the phase and the node. A
legitimate change to rehearse: it names a port the device lacks. **Rationale**: a push
refused is the one failure both platforms produce from intent alone, and M6/M7 verified it
(1.8); every verify assertion is consistent with the artifact by construction, so no
intent makes a new finding without a refusal. **Alternatives**: a role with an embedded
newline carrying a foreign line (rejected: an injection, not a change); a renamed device
(rejected: the node is recreated, not stepped).

<a id="r-15"></a>
### R-15 `fylgja-twin` retries a refused host until its own deadline; nothing waits in Fylgja

**Decision**: when `twin.rehearse` answers `run.in_flight`, `host.lab.present` or
`host.twin.present`, `fylgja-twin` waits 30 s and asks again, until its own deadline
(`timeout` less 180 s) nears, then `log_error`s naming the twin or the run the last
answer named. Every other refusal is final at once. The hand command is refused once.
**Rationale**: clarify's answer; the hand operator reads the refusal and acts.

<a id="r-16"></a>
### R-16 Cancellation from Infrahub's side: the interrupt is sent synchronously, and the deadline covers the rest

**Decision**: `fylgja-twin` keeps its own clock: it sends the interrupt
(`POST /v1/streams/{stream}/interrupt`) when its deadline nears while the answer is still
open, then concludes failure saying the run was asked to cancel; and it sends the same
interrupt from a `BaseException` handler with a **blocking** `httpx.Client` call, never an
`await` (1.4), so a check Prefect times out or cancels still asks its run to cancel. The
rehearsal's deadline (R-09) covers the case where neither reaches the server: the run cuts
itself and destroys. A connection lost mid-rehearsal (the answer cut before its document)
is `log_error`: the connection was lost, the run goes on to its destroy, no report will be
posted, re-run the checks once `twin show` reports no twin (FR-021, clarify's answer).
**Rationale**: 1.4 showed the stuck validator a timed-out check leaves, which the check's
own bound keeps from happening, and that only a synchronous call survives the cut.

<a id="r-17"></a>
### R-17 The server listens on every `--listen` given; the override and the bring-up script put it on the bridge

**Decision**: `fylgja serve --listen` becomes repeatable (cobra `StringArray`; one given
is as today, none is the default); each address is checked `host:port` before any
listens; every listener is opened before any serves, and a failure to listen closes the
others and refuses to start naming that address, exit 2; the report prints one listen
line per address with the port it got, each off loopback followed by its unencrypted
line; one `http.Server` serves every listener; a failure to accept on any is `serving on
<address>: <error>`, exit 2. The Compose override gives `task-worker` `extra_hosts:
["host.docker.internal:host-gateway"]`, `FYLGJA_API_ADDRESS: host.docker.internal:7650`
(a name Docker resolves, carrying no value of `local/.env`) and `FYLGJA_API_TOKEN:
${FYLGJA_API_TOKEN}` (from `local/.env`, which `--env-file` reads); `.env.example` says
so under `FYLGJA_API_ADDRESS`. The bring-up script's `fylgja` part starts the server with
`--listen 127.0.0.1:7650 --listen <bridge>:7650`, the bridge read from `docker network
inspect bridge` (`IPAM.Config[0].Gateway`), and `report_ok` requires both listen lines
and the unencrypted line; its `infrahub` part runs `compose up -d` whenever the override
was (re)installed, so a host set up before this feature recreates its task workers with
the entry and the variables (today it runs `up -d` only when a service is down).
`CLAUDE.md`'s start line and `docs/development.md`'s paragraph say the same. **Rationale**:
1.1 verified the address and the mechanism; FR-024–FR-026. **Alternative**: the task
workers on the host's network (rejected: the published Compose file is Infrahub's, and the
override must stay a pin and a cap beside it).

<a id="r-18"></a>
### R-18 Tier 2 proves the checks inside Infrahub through a test-only registration served from the bridge, against the server the task workers reach, and skips, saying so, where they reach none

**Decision**: a contract test in `internal/checks` (a Go package of tests over the
Python files and `.infrahub.yml`, with a `doc.go` and the registration's names as
constants) builds a bare repository from the tree's `.infrahub.yml`, `infrahub/checks/`
and `infrahub/queries/` under a `.infrahub.yml` of its own naming the two checks and the
one query alone (so the artifact definition is not registered twice), the definitions
under test-only names, `fylgja-test-step` and `fylgja-test-twin`, since whether Infrahub
accepts one check name from two repositories is unverified and after the import the
registration `fylgja` holds the real names, serves it with
`net/http` on `<bridge>:0` (the bridge found as the bring-up script finds it; skipped
when Docker reports none), registers it as `CoreReadOnlyRepository`
`fylgja-test-checks-<pid>` through test support, awaits the import and 15 s more for both
task workers' fetches (1.5), then seeds a throwaway branch, opens a draft proposed change
with two marks, and reads the two `CoreUserValidator`s and their `CoreStandardCheck`s:
`fylgja-twin` concluded success with `skipped a draft` in its message and booted nothing
(`twin show` through the API, no lab); `fylgja-step` concluded success with the plan's
text and the branch point's refusal in its message; then a stale mark, a re-run of the user
checks, and `fylgja-step` concluded failure naming `stage.artifact.stale` and the device.
It deletes the branch (its proposed change, comments and validators with it, 1.6) and the
registration (its definitions with it) in its cleanup, however it ends. **Where the task
workers reach no server** (`fylgja-step`'s message names the address as unreachable, or the
variable as unset), the test **skips** after the draft's skip is proved, printing why: CI's
contract job runs no server. On the development host it needs the operator's server on
the bridge (R-17) from this tree. **Rationale**: FR-029; the registration imports from
`origin`'s `main` alone (D-044), so the tree's checks reach Infrahub only through a
registration the test makes; tier 2 is allowed to write to Infrahub through test support.
**Alternatives**: a second permanent registration (rejected: two sets of checks would run
on every proposed change); the test starting a server on the bridge at 7650 (rejected: the
operator's holds the port, and the task workers' address is fixed by the override); a
Python test framework for the checks (rejected: Constitution I, one test framework; the
checks are glue, proved live).

<a id="r-19"></a>
### R-19 Tier 3's ninth case runs the live check through the operator's server on the bridge

**Decision**: case 9 is SR Linux alone (`PLATFORMS=nokia_srlinux` runs it). Before it, the
script requires the server the task workers reach: it asks `http://<bridge>:7650/v1/twin/show`
with `local/.env`'s token through a header file and fails, naming the remedy (`CLAUDE.md`'s
start line), unless `Fylgja-Build` is `bin/fylgja --version`'s; its own server stays on
loopback for its own commands. The case: a throwaway branch seeded, `-propose` (the draft's
creation runs both checks: `fylgja-twin` skipped it, `fylgja-step` passed), `-stage
seeded`, `-add-link`, the checksums awaited, `-stage third-link`, `-ready` (a new flag:
`is_draft` false), `-run-checks user` (a new flag; waits for every user validator
`completed`), then the `fylgja-twin` check read success with the report's text in its
message, one `CoreChangeComment` with the table, the drawing and the stages, and the
`twin.rehearse` run's history fetched; `twin show` reports no twin; then `-add-interface
n1:ethernet-1/99`, `-generate`, the checksums awaited, `-stage bad-port`, `-run-checks
user`, the check read failure naming `bad-port`, the phase `push` and n1, the second comment
with the reproduce commands, `head`'s row `not reached`; then `-delete`, after which
Infrahub holds nothing of the branch. The credential and marker greps extend to the two
comments' text and the two checks' messages, written to `$OUT`. The trap's destroy cancels
a rehearsal in flight (R-12). **Rationale**: FR-030, SC-010; the spec's assumption on the
server the case uses.

<a id="r-20"></a>
### R-20 The fixture tool and test support

**Decision**: `fylgja-fixture` gains `-ready` (sets the open proposed change's `is_draft`
to `false`, prints it), `-run-checks <artifact|user>` (`-run-check` stays as the
`artifact` form; `user` sends `check_type: USER` and waits until every `CoreUserValidator`
of the proposed change is `completed`, bounded 4,500 s, printing each check's name and
conclusion) and `-add-interface <device>:<name>` (one uncabled physical interface, enabled,
on a throwaway branch; `-generate` after it is the caller's, as after `-set-role`).
Test support gains `MarkReady(id)`, `RunUserChecks(id, timeout)`, `UserChecksOf(id)`
(`{Name, Conclusion, Severity, Message}` per `CoreStandardCheck` under a user validator),
`CommentsOf(id)` (`{ID, Text}`), `AddInterface(branch, device, name)`,
`ServeRepository(dir) (url, stop)` (a bare repository under a scratch directory, served
on the bridge) and `DeleteRepository(name)`. `-delete` is unchanged: a proposed change's
delete takes its comments and validators (1.6).

<a id="r-21"></a>
### R-21 How a check change reaches the development host's Infrahub

**Decision**: the development host's registration imports from `origin`'s `main` on
`InfrahubReadOnlyRepositoryImportLastCommit`, which the operator asks for once the
checks are pushed there; `docs/development.md` says to wait for both task workers' fetches
(about 15 s after the import's own flow, 1.5) before a run-check, and that a branch made
before the import runs the new checks only after a rebase or when recreated (1.5). Until
then, tier 2's registration (R-18) is how the tree's checks run here, and tier 3's case 9
runs the registered ones: **case 9 passes only once the checks are on `origin`'s `main`
and imported**, which the plan's order puts before the live tasks (an `[operator]` push and
import). **Rationale**: D-044 and 1.5.

<a id="r-22"></a>
### R-22 What the records say, and the decision entries

**Decision**: the glossary gains *rehearsal*, *baseline stage* and *baseline finding*
(distinguished from M11's *baseline*), *check (Infrahub)*, *bridge listener* and
*reclaim*; `SECURITY.md` gains the bridge listener's paragraph (FR-027); the roadmap marks
F-007 and F-008 built and rewords F-007's row (the check logs the plan as text and posts
no comment); the architecture's §4.4 gains the fifth workflow and its drawing, §4.6 the
command and the checks as a client inside the task worker, §6 the rehearsal's limits (the
deadline, a fault reproducible by hand, the bridge); `contracts/api.md` and `cli.md` each
gain "015: the rehearsal"; `CLAUDE.md`'s State, Formats, the worker's workflow count (five)
and the server's start line move. The four decision entries are drafted in §3 for the
operator, as 014's D-046 was, and tagged `[operator]` by `tasks`.

---

<a id="3-entries"></a>
## 3. The decision entries, drafted

Each in the log's format, to be appended as D-049 to D-052 once the operator accepts them
(at `analyze`, as D-046 was), before the code each governs is built.

> **D-049 — A check posts the rehearsal's report as a comment; Fylgja writes nothing.**
> Beside [D-026](../../docs/decisions.md#d-026). Context: F-007 and F-008 bring the
> rehearsal inside Infrahub's proposed-change workflow, whose unit of writing is a comment
> rendered as markdown, while Constitution III keeps every operation Fylgja makes on
> Infrahub a query. Verified on 1.11.2 (2026-10-17, §1.3): a check runs in Infrahub's task
> worker with the source branch and the worker's own client, may create a
> `CoreChangeComment` on the proposed change, and its own message is plain text. Options:
> Fylgja posting the comment through the API's server (rejected: a write to Infrahub, III);
> the report in the check's message alone (rejected: a check's message renders as code, not
> markdown); a comment edited on each run (rejected: Infrahub's comment carries no stamp,
> and a history of rehearsals should stay readable). Decision: the two checks this
> repository ships, `fylgja-step` and `fylgja-twin`, are clients of the API and glue;
> `fylgja-twin` posts one new `CoreChangeComment` per run, carrying the report's markdown
> headed by the run and when the stages were resolved, edits and deletes none, and writes
> nothing else; `fylgja-step` writes nothing. A comment that cannot be posted is logged and
> fails nothing. Consequences: a proposed change's comments are the rehearsals' history; a
> test's proposed change goes with its comments when deleted (§1.6); D-026 stands.

> **D-050 — The API's server listens on the host's Docker bridge beside loopback, in
> plaintext, under the one token.** Supersedes the loopback default of
> [D-042](../../docs/decisions.md#d-042) for this deployment; D-042's token and comparison
> stand. Context: Infrahub's task workers run on a Compose bridge where neither loopback
> nor `host.docker.internal` reaches the lab host (§1.1). Verified (2026-10-17): with
> `extra_hosts: host.docker.internal:host-gateway`, a container on that network resolves
> the name to the host's docker0 address (`172.17.0.1` by Docker's default) and reaches a
> server bound there with the token, and is refused without it. Options: a relay container
> (rejected by the brief: a second process to run and keep); server TLS (rejected by the
> brief and D-042: a key file would be the first credential read from a file); the task
> workers on the host's network (rejected: Infrahub's Compose file stays Infrahub's).
> Decision: `fylgja serve --listen` is repeatable; on the lab host the server listens on
> `127.0.0.1:7650` and on the bridge's address, `<docker0>:7650`, the override giving the
> task workers the host-gateway entry, `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`; the
> bring-up script starts it so. Consequences: any container on the host can reach the API,
> the twin's nodes included, and the bearer check is what guards it; the token is in the
> task workers' environment and in `local/.env`; `SECURITY.md` says so; D-042's revisit for
> a client that needs less than everything stays deferred.

> **D-051 — `twin rehearse` is a fifth short workflow, `fylgja-rehearse`, that runs
> provision, step and destroy as children under their fixed ids, with a deadline derived
> from the stages' budgets.** Beside [D-007](../../docs/decisions.md#d-007) and
> [D-036](../../docs/decisions.md#d-036). Context: a rehearsal is a create, a verify, a
> step and a verify per later stage, and a destroy, run unattended for minutes, and must
> destroy its twin whatever happens (FR-005). Options: the server driving the runs one by
> one (rejected: it keeps nothing between requests, D-014, and D-040 leaves a run running
> when its client goes); one workflow scheduling the activities (rejected: it repeats the
> three workflows' logic and cleanup); a long-running workflow (rejected, D-007).
> Decision: `fylgja-rehearse`, a fixed id, whose children are `fylgja-provision`
> (already compiled), `fylgja-step` (allowing restarts, with the default wait) and
> `fylgja-destroy` on a disconnected context, and whose baseline wait is `VerifyTwin`; it
> is refused beside any run in flight, and `twin destroy` cancels it and waits for its
> destroy; its deadline is the sum of its stages' provision, step and wait budgets from the
> packages and the mechanism constants, under a ceiling of Fylgja's own (3,600 s), enforced
> by a timer that cancels the children and then destroys; its twin's record names it, and a
> rehearsal whose run is no longer running is destroyed by the next (the reclaim).
> Consequences: Constitution VIII's count of workflows is five; the twin record moves to
> `7`; a step cut by the deadline records diverged (D-036) before the destroy; the twin
> record's rehearsal mark is the only new state.

> **D-052 — The check concludes from the report's status alone; Fylgja's verdicts stay
> advisory.** Beside [D-039](../../docs/decisions.md#d-039). Context: a stage that fails
> must block the merge (F-008), while D-039 keeps every Fylgja report advisory and no
> Fylgja operation reads one. Options: Fylgja refusing something on a failed stage
> (rejected: D-039); the check reading the stages' verdicts (rejected: two places deciding
> what fails). Decision: `twin.rehearse`'s document carries the verdicts and the status, and
> the check maps the status alone: `ok` is success, every other status is failure, the
> report's text the message either way; a draft is skipped with success; `fylgja-step`
> fails only on a refusal as intent, the stages unlistable, or Fylgja unreachable, a branch
> point refused for want of a network on `main` excepted (the one rule the Python holds, read
> from the finding's rule and `at_source`; a later `stage.plan` that carries the distinction
> itself retires it). Consequences: the merge is gated by
> Infrahub's own rule over the check's conclusion; nothing in Fylgja acts on the rehearsal;
> the roadmap's F-007 row is reworded (no comment from `fylgja-step`).

---

<a id="4-owed"></a>
## 4. Owed at implement

- **The override and the server on the bridge, on the development host**: the override
  copied beside the published file, the task workers recreated (`compose up -d`), the
  server restarted with both `--listen` flags from this tree; verified by a request from
  inside a task worker with the token and without (§1.1's probe, on the real server).
- **The checks on `origin`'s `main`, imported**: the operator pushes and asks
  `InfrahubReadOnlyRepositoryImportLastCommit`; both task workers' fetches waited for (§1.5)
  before any run-check. Tier 3's case 9 and the README's walk-through need it (R-19, R-21).
- **The hand scenarios**, then `docs/verified-facts.md`: the comment's table and Mermaid
  and a long message looked at in the UI (§1.8); the deadline cutting a stage (a step made
  to hang is the hard part: a wait that never settles costs its 120 s budget alone, so the
  deadline is proved at tier 1 under the test suite and by hand with a ceiling lowered
  through a test seam, never a flag); the operator's interrupt during a step; a client gone
  mid-rehearsal (`twin show` naming the run, the twin destroyed at the end); the reclaim
  (a rehearsal killed with its worker stopped and restarted, then the next rehearsal
  destroying its twin).
- **The push refused for `ethernet-1/99`** on the rehearsal (R-14, §1.8), at tier 3.
- **The four decision entries** (§3), the operator's at `analyze`.
- **`make diagrams`** after the C4 model moves (R-11, the checks' container, the bridge in
  the deployment view).

---

<a id="5-verified-at-implement"></a>
## 5. Verified at implement

### 5.1 The server on the bridge, from inside a task worker (2026-10-19, 18:19Z; T037, SC-009)

The override was applied in the loop's Run 10 (16:26Z: both task workers recreated, the
other six services untouched), and the operator's two runs of the bring-up script's
`fylgja` part left the server on both addresses (T036). This run restarted both processes
from this tree and asked the server from where Infrahub's task workers stand. No twin was
booted and no token was printed: the token was compared by its sha256 alone.

- **Rebuilt and restarted** (18:19:05Z–18:19:24Z). `make build` relinked `bin/fylgja`
  (a new inode, since the operator's commit had moved the stamp), which left the worker
  and the server on a `(deleted)` binary; both were stopped with `pkill -x fylgja` and
  started with `CLAUDE.md`'s two lines, statically linked, `0.1.0-dev`. Each `exe` reads
  `bin/fylgja`, not deleted; each environment carries `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN`, both logins, `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`. The
  server's report: `listening on 127.0.0.1:7650 (API version 1, build 0.1.0-dev)`, then
  `listening on 172.17.0.1:7650 (…)` followed at once by `172.17.0.1:7650 is not a
  loopback address: the API's token is sent unencrypted on it`, and both packages with
  their logins set. The worker's: both packages, `host: lab fylgja absent; twin directory
  absent`.
- **From inside each task worker** (18:19:41Z–18:19:43Z), quickstart §2's `python -c`
  request to `http://$FYLGJA_API_ADDRESS/v1/twin/show`: with the container's token, `200`,
  `Fylgja-Api-Version: 1`, `Fylgja-Build: 0.1.0-dev`; without it, `401`. The same from
  `task-worker-1` and `task-worker-2`. **From the host**, `curl` to `172.17.0.1:7650`
  without the token: `401`. The server logged one line a request, `twin.show` `ok` (126 ms
  and 110 ms) or `token_refused`, naming no address, and its log since the restart holds
  no token.
- **`docker inspect` of both task workers** (created 16:26:07Z, image `1.11.2`):
  `ExtraHosts` is `["host.docker.internal:host-gateway"]`, and `getent hosts
  host.docker.internal` inside each answers `172.17.0.1`, the bridge's gateway; the
  environment holds `FYLGJA_API_ADDRESS=host.docker.internal:7650` and `FYLGJA_API_TOKEN`,
  equal to `local/.env`'s by its sha256. No other `FYLGJA_*` name is there.
- A client's `twin show`, from an environment holding the token alone, answered `twin:
  none: no lab fylgja, no twin directory`, exit 0, over loopback.
