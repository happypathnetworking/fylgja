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
the bridge (R-17) from this tree (*proved from T073: once a check has reached a server, the
test fails unless the `fylgja serve` listening on the bridge runs this tree's
`bin/fylgja`, read at `/proc/<pid>/exe`, and says so when that cannot be read*).
**Rationale**: FR-029; the registration imports from
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
start line), unless `Fylgja-Build` is `bin/fylgja --version`'s (*and, since every unstamped
build is the same version, unless the server's process runs this tree's `bin/fylgja`,
neither `(deleted)` nor another file: T073*); its own server stays on
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

### 5.2 The rehearsal by hand, on real twins (2026-10-19, 18:46Z–19:17Z; T041, SC-001–SC-004)

Quickstart §3 on `fylgja-test-qs-2221702`, three SR Linux nodes, through the server on
loopback, from `bin/fylgja` rebuilt at 18:46Z. The worker and the server were restarted
from it and verified as `CLAUDE.md` says (each `exe` current; `INFRAHUB_*`, both logins,
`FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN` in each environment; both listen lines and the
bridge's unencrypted line; both packages with their logins set; `lab fylgja absent; twin
directory absent`). `free -m` read 18.5 GiB available, load average 1.9. The dev server
was up. No token, password or configuration line is in any output: each output and the
scratch servers' logs were matched with `grep -c` against each value and never printed.

- **The composition** (18:47:12Z–18:48:31Z): the seed 24.1 s; a draft proposed change
  `18e002bb-e29b-7f8f-33be-c51093ae2f38` in 39 s, three validators; `seeded` at
  `18:48:16.255359`; `-add-link`, n1's and n3's checksums moved within 7 s; `third-link`
  at `18:48:31.087099`. `stage plan`, exit 1 on the branch point's rejection as 014's
  plan ends: the branch point refused `contract.node.missing`, `seeded` `d4012c00…`,
  `third-link` `c29aba04…`, `head` `41899b0a…`, `third-link → head` unchanged, "the ids
  differ by provenance alone". `head`'s `at`, the branch's latest stamp, precedes
  `third-link`'s, which was written after it.
- **1. Every stage passes.** Text (18:48:52Z), run `fylgja-rehearse
  01a1557e-dfac-7d86-9984-951c1e2f533d`: the heading `4 stages; deadline 32m30s (ceiling
  1h0m0s)`, the branch point's refusal under it, `seeded … ; baseline`. The provision's
  deploy 45.0 s, readiness at most 0.4 s, the pushes 2.4–2.7 s; the baseline settled
  after 4.3 s (1 read), 15 held; `third-link` stepped in 4.6 s (push n1 2.7 s, n3 2.8 s),
  settled after 5.4 s, 19 held, passed; `head` unchanged in 1.0 s, settled after 4.4 s,
  passed; the destroy's teardown 2.2 s; `rehearsal ok: 3 stages rehearsed, every one
  passed; the twin is destroyed; 72.0s of the 1950s deadline`, exit 0, 82.4 s wall.
  `twin show`, asked during the destroy, named the record `of rehearsal run
  fylgja-rehearse 01a1557e-…`, the run `destroying the twin, step teardown`, and the
  in-flight line its destroy child; afterwards no twin. `--json` (18:50:47Z): exit 0,
  86.9 s, status `ok`, rows `refused`, `baseline`, `passed`, `passed` with no new
  finding, `deadline_s` 1950, `used_s` 75.1, `reproduce` `[]`, `reclaimed` `null`, the
  destroy's `removed` the lab (3 containers) and the twin directory, nothing on stderr;
  the document validates against `contracts/findings.schema.json` with every contract
  schema. `--markdown` (18:52:55Z): exit 0, 73.8 s; stdout the heading naming the
  proposed change and its branch, the run line with `resolved_at`, `ok` and 62.9 s of the
  1,950 s deadline (ceiling 3,600 s), the table's four rows, the drawing (the branch
  point's edge dotted `not computed`, `seeded → third-link` naming the link, the two nodes
  changed and their reasons and the artifacts by node, `third-link → head` `unchanged`),
  Stages, Warnings `none`, Baseline findings `none`, the caveat, and no Reproduce block;
  the progress and the findings on stderr.
- **2. The failing stage** (18:54:27Z–18:57:56Z). `-add-interface n1:ethernet-1/99`,
  `-generate` (n1's checksum alone moved), `bad-port` at `18:54:27.347172`. The plan:
  5 stages, deadline 43m0s (2,580 s), `bad-port` and `head` each warned
  `artifact.interface.unrepresented` at read and at compile, with
  `omit.interface.unmappable`. The run: the baseline and `third-link` as before; `bad-port`'s
  push to n1 `push.refused` (checksum `6237e7f9…`, D-035's message); `bad-port: diverged at
  phase push: landed none; not landed n1 (push.refused); settled after 5.9s (1 read); 19
  held, 0 failed, 0 skipped; failed`; `head: not reached`; `rehearsal nonconforming:
  stage …/bad-port failed at phase push; the twin is destroyed; reproduce it by hand:`
  and **five** commands, not the four quickstart §3 and T041 count: `twin create --stage
  …/seeded`, `twin step --stage …/third-link --allow-restart`, `twin step --stage
  …/bad-port --allow-restart`, `twin verify`, `twin destroy`. T013's rule steps through
  every rehearsed stage up to the failed one, and `bad-port` is the second; the contract's
  example has four because its failed stage is the first. Exit 5, 90.0 s; the rejections
  `contract.node.missing`, `push.refused`, `rehearsal.stage.failed` and `step.diverged`.
  **By hand**, the five commands: the create, exit 0 (52 s); the step to `third-link`,
  exit 0 (stepped in 4.8 s, settled after 5.7 s); the step to `bad-port`, exit 4,
  `push.refused` on n1 with the same checksum, landed none, diverged at `third-link`;
  `twin verify`, exit 5 (its 19 reads held; three `verify.record.holds` failed, the
  record's claim that the nodes hold `c29aba04…`, not the staged `49ab82e2…`); `twin
  destroy`, exit 0,
  the lab and the twin directory removed.
- **3. The interrupt** (18:58:10Z): `SIGINT` to the client at 18:59:12.3Z, during
  `third-link`'s step at reconcile. `run cancelled; waiting for its destroy`; the step
  child finished its reconcile and recorded the twin diverged; the destroy ran (teardown
  1.8 s). `third-link: cancelled at phase reconcile; error: the run was cancelled`, the two
  later stages `not reached`, `rehearsal error: the run was cancelled at stage
  …/third-link; the twin is destroyed`; `run.cancelled` for the rehearsal (filed at step
  `record`, the last step its child reached before the destroy) and for the step child (at
  reconcile), and `step.diverged`. Exit 2, 65.9 s; no twin, no lab.
- **4. Beside a create of my own** (18:59:27Z): while `twin create --stage …/seeded`
  deployed, `twin rehearse` was refused `run.in_flight` at `start`, naming
  `fylgja-provision 01a15588-8037-…`, exit 1, in 8.1 s: the five stages are planned
  first (R-02's order), and nothing waits for the create or starts. The create ended
  exit 0. A rehearsal beside that hand twin (19:00:27Z) was refused `host.lab.present`
  and `host.twin.present` at `host_check`, exit 1, in 10.0 s, and not reclaimed, since
  its record names no rehearsal; `twin destroy` cleared it.
- **5. A client gone** (19:00:48Z): the client killed with `SIGKILL` at 19:00:59.8Z, in
  the baseline's deploy; the server logged `twin.rehearse` `client_gone` after 10.8 s. `twin
  show` then read `kind: none; run fylgja-provision 01a15589-d5c9-… is at step deploy, and
  the host holds its work; rehearsal run fylgja-rehearse 01a15589-d570-… is at stage
  …/seeded, step deploy`, and `in flight: run fylgja-rehearse … at step provision (run
  fylgja-provision … at step deploy), creating the twin at stage …/seeded`. At 19:01:50Z:
  `kind: pinned at …, stage …/seeded, of rehearsal run fylgja-rehearse 01a15589-d570-…;
  not following; rehearsal run … is at stage …/third-link, step reconcile`, and the
  in-flight line its step child `stepping towards stage …/third-link`. By 19:02:17Z no
  twin, nothing in flight, no lab. The run's own result, read from its history: outcome
  `stage_failed` at `bad-port`, the verdicts `refused`, `baseline`, `passed`, `failed`,
  `not_reached`, 75.4 s used, the destroy's removals. The report reached no one but the
  history, as the spec's edge case says.
- **6. The reclaim.** (a) 19:02:43Z: the worker killed with `SIGKILL` at 19:02:59.0Z, five
  seconds into the baseline's deploy; `clab deploy` outlived it, the three containers up.
  `twin show` named the rehearsal and its provision child at deploy, and a second
  `twin rehearse` (19:03:37Z) was refused `run.in_flight` naming the rehearsal run
  `01a1558b-93aa-…`, exit 1, in 10.4 s: the spec's "the worker dies mid-rehearsal".
  **A run with no worker cannot end by itself**: it has no execution timeout, and its own
  destroy needs a worker. Quickstart §3's "wait for the provision to be abandoned" needs
  the run ended, and the one end that runs no destroy is the operator's terminate:
  `temporal workflow terminate` at 19:03:55Z. Its provision child, under
  `ParentClosePolicy` `ABANDON`, lived on. The worker was restarted at 19:05:06Z and
  verified; its start-up report read the lab present with no record, an orphan. The
  deploy's next attempt said `lab already present at deploy: recreating it with
  --reconfigure`, and the child ended ready (the deploy 179.8 s in all), recording at
  19:05:56.8Z `stage …/seeded, of rehearsal run fylgja-rehearse 01a1558b-93aa-…; not
  following`. The first client, still following, answered only once that abandoned child
  closed: `operation.failed [step record] … waiting for run 01a1558b-93aa-…: workflow
  execution error (…): terminated`, exit 2, after 193.2 s. Then `twin rehearse --json`
  (19:06:09Z): `reclaimed` naming the run, its destroy having removed the lab (3
  containers) and the twin directory; the warning `rehearsal.twin.reclaimed` at `destroy`,
  naming the destroy run `01a1558e-b93e-…`; then the run, `nonconforming` at `bad-port`,
  exit 5, 92.0 s. (b) In text, with the worker up: a rehearsal terminated at 19:08:55.8Z
  during `third-link`'s step; the abandoned step child stepped and settled (6.0 s), and its
  record kept the rehearsal's mark (`stage …/third-link (stepped from …/seeded by run
  fylgja-step 01a15591-1b01-…), of rehearsal run fylgja-rehearse 01a15590-5faf-…`); that
  client ended `operation.failed` (`terminated`), exit 2. `twin rehearse` (19:09:13Z)
  printed, after the plan, `reclaiming the twin of rehearsal run
  01a15590-5faf-7a97-b502-69c3df9ea908`, `run fylgja-destroy 01a15591-8a80-…`, its steps,
  `removed lab fylgja (3 containers)` and `removed twin directory …`, then `run
  fylgja-rehearse 01a15591-93d2-…` and the rehearsal, `nonconforming`, exit 5, 81.9 s,
  with `rehearsal.twin.reclaimed`.
- **7. The deadline.** Two servers were built into the scratchpad from `git archive HEAD`,
  each run on `127.0.0.1:7651` beside the tree's and stopped after its one request; the
  tree, the worker and every flag were untouched. **The ceiling lowered**
  (`server.Server.RehearsalCeiling` set to 30 min in `serve.go`): the heading read
  `deadline 43m0s (ceiling 30m0s)`, then `rehearsal.deadline.unfit` at `start`, "the stages
  need 43m0s (2580s) …, over the ceiling of 30m0s (1800s)", exit 1, 8.9 s, no run started.
  **A lowered ceiling cannot cut a stage**: the run is given the deadline the stages'
  budgets sum to, and the ceiling only refuses one over it before any run (R-02, R-09).
  **The deadline lowered** (the server's computed deadline replaced by 62 s in
  `rehearse.go`, so the run's `DeadlineS` was 62): 19:12:16Z, the heading `deadline 1m2s`;
  the baseline 48.9 s (deploy 40.5 s), `third-link` passed in 10.4 s; the timer fired in
  `bad-port`'s step at push, as n1 refused the push; the step child was cancelled and
  recorded the twin diverged, and the destroy ran (teardown 1.8 s). `bad-port: cancelled
  at phase push; error: the deadline passed`, `head: not reached`, `rehearsal error: the
  deadline of 62s passed at stage …/bad-port; the twin is destroyed`; the rejection
  `rehearsal.deadline.cut` at `push` "…: …/seeded took 48.9s, …/third-link took 10.4s", and
  the step child's `run.cancelled`. Exit 2, 80.4 s; no twin.
- **A defect, fixed**: the rehearsal's text never said what its own destroy removed. The
  contract's text has `removed lab fylgja (3 containers)` and `removed twin directory …`
  after the destroy's steps, as `twin destroy` and the reclaim print them, and `twin.rehearse`
  printed neither. The server now prints them (`printCleanup`) once the run has closed,
  before the stage lines; `internal/cli`'s `TestRehearseText`, which pins stdout whole,
  holds the two lines and failed before the fix. Rebuilt, with the worker and the server
  restarted and verified, `twin rehearse --markdown` (19:15:30Z) printed the two lines on
  stderr after the destroy's steps. Its stdout was the failure's markdown: `nonconforming`,
  77.2 s of 2,580 s; `bad-port`'s row `diverged at push 6.7s; not landed n1 (push.refused)`;
  the drawing's `third-link → bad-port` edge `~n1 (mapping); artifacts n1`; the Findings;
  the Reproduce block with the five commands. Exit 5, 90.1 s.
- **Seen, not changed** (for converge): the markdown's Warnings list a warning once per
  stage and step that filed it, naming no stage (four identical
  `artifact.interface.unrepresented` lines here, read and compile for `bad-port` and
  `head`), as the plan's warnings carry over. A client following a rehearsal that is
  ended outside Fylgja (a terminate) answers only once the abandoned children close, which
  with no worker is never: `Follow` follows each child to its end. The baseline's verify
  line carries no counts (T029's departure).
- **Left clean** (19:17:13Z): `-delete` removed 3 stages, the proposed change and the
  branch. `Branch` lists `main` and `fylgja-fixture`; 0 proposed changes, stages, comments
  and check definitions; the one registration `fylgja`; `clab inspect --all` `{}`; no
  `local/twin`; no Schedule; no workflow running.

### 5.3 One query name in two registrations (2026-10-19, 19:36Z; T045)

T045 asks, before the checks' first import, whether two read-only repositories may each
register a `CoreGraphQLQuery` named `fylgja_branch`, as the test's registration and `fylgja`
would once T054 has imported the checks. `GET /api/schema` on `main` already says
`CoreGraphQLQuery` and `CoreCheckDefinition` each carry `name` `unique: true` and the
uniqueness constraint `[name__value]`. A probe, a throwaway test since removed, served two
repositories from the bridge with `testsupport.ServeRepository`, each holding only
`.infrahub.yml` and the tree's `infrahub/queries/branch.gql` registered as `fylgja_branch`,
and registered them as `fylgja-test-probe-a-<pid>` and `-b-<pid>`.

- **The first imports**: its query was on `main` 15 s after the create, under its own
  repository, `sync_status` `syncing` then `in-sync`.
- **The second does not**: 16 s after its create its `sync_status` read `error-import`
  (`operational_status` `online`), and it stayed so for the 94 s read. Its `Adding read only
  repository` and `Pull latest commit` flows ended `Failed` on `CoreGraphQLQueryCreate`:
  `Violates uniqueness constraint 'name'` (`http_status` 422). `fylgja_branch` stayed the
  first's alone, and nothing of the second was imported: an import stops at its first
  refused object, so a registration whose query collides registers no check either.
- **Both deletes** removed their registrations and the query: afterwards `CoreReadOnlyRepository`
  held `fylgja` alone, `CoreGraphQLQuery` `device_config` alone, and `CoreCheckDefinition`
  counted 0.
- Seen beside it: the two served repositories, of identical files committed in the same
  second by the same fixed author, had the same commit (`0edef100…`).

**So the test's scratch copy renames the query**: each class's `query = "fylgja_branch"`
becomes `query = "fylgja_test_branch"`, registered under that name beside the test-only check
names, and T054's re-run of the test is what proves the two registrations coexist.

### 5.4 `fylgja-step` run outside Infrahub, against the real one (2026-10-19, 19:30Z–19:35Z; T042, T043)

Before any import, the check's class was run on the development host with the venv's SDK
(1.23.2), as Infrahub's task worker would run it but for the process: the tree's
`infrahub/checks/` laid out as `commits/<sha>/infrahub/checks/` with no `__init__.py` and
imported by `importlib.import_module("commits.<sha>.infrahub.checks.fylgja_step")`, the module
name `extract_repo_file_information` gives it (read from the task worker's
`/source/backend/infrahub/git/base.py`; `integrator.py` imports a check that way). **The
relative import `from .fylgja_api import …` resolves** under it, the directories being namespace
packages, so no `__init__.py` is added. The client was an Admin `InfrahubClient`; the API was
the operator's server on loopback, through `FYLGJA_API_ADDRESS=127.0.0.1:7650`; `run()` was
handed the query's answer, since `fylgja_branch` is not yet registered. No token was printed:
each message was checked for both tokens and held neither.

- **The glue's faults** (`call` against the server): a closed port `the API at 127.0.0.1:1 cannot
  be reached: All connection attempts failed`; an unknown host `… cannot be reached: [Errno -2]
  Name or service not known`; a wrong token `… refused this check's token (FYLGJA_API_TOKEN)`;
  `/v9/…` `answered 404 Not Found`, since its `Fylgja-Api-Versions` names `1` (the server
  logged `version_unknown`), as the Go client reads it; an address with a user `FYLGJA_API_ADDRESS
  is not host:port …: nothing was sent`; each variable unset, and a token ending in a carriage
  return, refused naming the variable with nothing sent; an interrupt for no open answer `the
  answer the interrupt names has ended`. `stage.plan` on `fylgja-fixture`: no out or err frame,
  the document `rejected` with `stage.unknown`, its text the findings.
- **The plan passed** on `fylgja-test-step-smoke-2617353` (the fixture tool: seed, `-propose`,
  `seeded`, `-add-link`, the checksums awaited, `third-link`): `passed=True` in 9.9 s, the
  message the plan's text (four stages, three steps, the branch point `refused
  (contract.node.missing)`), then the findings' text with the one rejection, as information.
  Every frame of the plan was an `out` frame; none was `err`.
- **A stale mark failed it**: `-set-role stale-role`, then `role-stale`: `passed=False` in
  7.6 s, the `log_error` the findings' text, `stage.artifact.stale` on n1, n2 and n3 for
  `role-stale` and for `head`.
- `-delete` removed 3 stages, the proposed change and the branch; Infrahub read as it began.

### 5.5 The checks inside Infrahub, and tier 2 whole (2026-10-19, 20:04Z–21:22Z; T050, SC-005, SC-010)

Run 15's rebuild had left the worker and the server on a `(deleted)` binary. `make build`,
then both stopped with `pkill -x fylgja` and started with `CLAUDE.md`'s two lines, and
verified: each `exe` current, each environment carrying `INFRAHUB_*`, both logins,
`FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`; the two listen lines, the bridge's followed by its
unencrypted line; both packages with their logins set; from each task worker `200 1
0.1.0-dev`. They were restarted the same way after the fixes' rebuild (20:45Z). `free -m`
read 18.4 GiB available, load average 2.4; the dev server was up. No twin was booted:
`clab inspect --all` read `{}` and `local/twin` was absent throughout. No token was printed.

- **`TestChecksInsideInfrahub` alone** (20:05:09Z): **PASS in 198.7 s** (200.6 s wall with
  the compile), not skipped. The registration imported in 11 s, the branch seeded in 18 s,
  the draft's pipeline concluded after 58 s, the re-run with two marks `success` after 37 s
  (a message of 2,266 characters), the stale mark's `failure` after 31 s (5,131). A poll of
  `CoreUserValidator` on `main` every 2 s beside it read each validator's stamps:
  **`fylgja-test-step` took 18.9 s at the draft's creation, 13.6 s at the re-run with two
  marks and 12.4 s with the stale mark** (`started_at` to `completed_at`), well inside
  SC-005's minute; `fylgja-test-twin`'s skip took 13.4 s, 5.2 s and 4.0 s. The server logged
  three `stage.plan` (`rejected`, the branch point's refusal or the stale mark; 6.4 s, 8.7 s
  and 8.3 s) and two `twin.show`. Afterwards `main` and `fylgja-fixture` alone, 0 proposed
  changes, stages, comments, check definitions and user validators, the query
  `device_config` alone.
- **Tier 2's first run** (20:09:02Z–20:39:07Z, 1,805.1 s, exit 2). Three tests failed at
  `OpenProposedChange`'s 180 s bound on the pipeline, all between 20:10Z and 20:15Z:
  `TestChecksInsideInfrahub` and `internal/stages`' `TestStagesListAndPlan` with the artifact
  validator still `in_progress`, `TestRehearseRefusesBeforeAnyRun` with its last read cut
  (`EOF`: Infrahub dropped the connection). Seeding a branch took 72–96 s there against 18 s
  alone. And `internal/server` reached `go test`'s 30-minute timeout:
  `TestRehearseComposedByTheFixtureTool`'s `-run-checks user` had waited 24 minutes.
  - **What hung.** That test's branch was made at 20:14:24Z, while the checks' registration
    lived on `main` (imported 20:09:43Z, deleted about 20:15:20Z). Once it was deleted, `main`
    held no definition, so the test's guard ran the user run; but the branch still listed
    `fylgja-test-step` and `fylgja-test-twin`, each with `repository` null, and
    `RunUserChecks` waited for both. **Infrahub never runs them**: a run-check's
    `trigger_user_checks` (the task worker's `/source/backend/infrahub/git/tasks.py`) runs, for
    each repository in the branch's diff, that repository's `checks` as the source branch
    sees them, and a repository is branch-agnostic, so a deleted one is in no branch's diff. A
    throwaway probe, since removed, held it: with a registration, a new branch's two
    definitions name its repository; after the registration's delete the branch still lists
    both, `repository` null; a draft's user run then returned none in 0.6 s with the fix
    below. The killed package's cleanup never ran: its branch and proposed change were
    removed with `fylgja-fixture -delete` (`deleted 0 stages, 1 proposed change`), its
    fixture tool's process killed and its temporary directory removed.
  - **Seen beside it**: while the registration lived, other packages' proposed changes ran its
    checks, as every proposed change runs every registered repository's: Prefect ran
    `git-repository-trigger-user-checks` for `fylgja-test-checks-2706159` and for `fylgja` on
    a stage test's draft (both `Failed` on its branch, already deleted). Prefect lists no
    artifact generation and no user check as a flow run, so the stall itself is not
    attributed; flow runs started about 20 s after they were scheduled throughout.
  - **Fixed** (US2, US3's test support): `checkDefinitionsOn`, which `RunUserChecks` waits on,
    lists the definitions of a repository still registered; the fixture tool's line reads
    `no user check ran on proposed change <id> on <b>: the branch sees no check definition of
    a registered repository`. `OpenProposedChange`'s bound is `pipelineWait`, 6 minutes.
- **Tier 2's second run** (20:45:47Z–21:03:02Z, 1,034.7 s, exit 2): every package passed but
  `internal/checks`. Its draft's pipeline concluded after 260 s, then n1's render after the
  third link outlasted `checksumWait`'s 90 s (n3's moved, n1's did not). Pipelines elsewhere
  concluded after 249 s, 185 s, 151 s, 134 s, 38 s and 23 s. While the registration lived,
  two other packages' drafts, `TestRehearseRefusesBeforeAnyRun`'s and a stage test's, ran
  `fylgja-test-step` (53.9 s and 62.3 s) and `fylgja-test-twin` (44.9 s and 49.3 s), their
  plans reaching the server, beside the test's own (57.5 s and 46.2 s). The fixture tool's
  branch, made while it lived, returned at once (`-run-checks user: 2.7s`, the new line).
  - **Fixed**: `make test-contract` runs `internal/checks` after the rest, alone, in a second
    `go test`, running both whatever the first answers and failing if either does. Its
    registration makes every proposed change opened while it lives run its two checks, and
    its waits, and SC-005's minute, are an otherwise idle Infrahub's. The package set is the
    same 24 (`go list -tags contract ./...`).
- **Tier 2's third run** (21:03:29Z–21:21:49Z): **`ok` in 1,099.7 s wall, exit 0**, every
  package `ok`, no test skipped and none failed; **383 s longer than 014's 716.7 s**. The rest
  ran in about 900 s (`internal/stages` 894.0 s the longest, `internal/stage` 648.4 s,
  `internal/server` 606.1 s, `internal/intent` 254.3 s), then `internal/checks` in 199.5 s.
  `TestRehearseRefusesBeforeAnyRun` passed in 299.8 s (its pipeline 192 s, the refusal in
  8.7 s), `TestRehearseComposedByTheFixtureTool` in 303.7 s (`-run-checks user` 2.2 s, the
  checks' registration having lived beside its branch), `TestChecksInsideInfrahub` in
  199.5 s: imported in 21 s, seeded in 13 s, the draft's pipeline 56 s, the re-run `success`
  after 38 s and the stale mark's `failure` after 26 s, the time from the run-check to the
  conclusion, which bounds `fylgja-test-step`'s own from above, inside SC-005's minute. Its
  three plans answered in 4.7 s, 7.6 s and 6.8 s. Pipelines beside each other, with no
  registration but `fylgja`, still concluded after 192 s and 176 s: the 180 s bound would
  have failed again.
- **After it**, quickstart §5's query read `main` and `fylgja-fixture`; 0 proposed changes,
  stages and comments; the one registration `fylgja`; 0 check definitions, as before T054.
  `clab inspect --all` `{}`, no `local/twin`. The three runs' outputs and the solo run's were
  searched for each token, password, secret key and login by its value: none, but for the
  images' five-character default inside `admin-state` and a containerlab log in the tests'
  data.

### 5.6 The checks on `origin`'s `main`, imported on the host's registration (2026-10-19, 23:25Z–23:36Z; T054, R-21)

The operator pushed this branch to `origin`'s `main` at 23:25:24Z, `9cba3c9` → `999456e`, a
fast-forward (T054's note); at 23:28Z `git ls-remote origin` read `999456e` as
`refs/heads/main`, this branch's head one commit ahead of it with a note in `tasks.md` alone.
From `5207aae`, the registration's commit, `999456e` adds the two checks, their shared module,
the query `fylgja_branch` and their `.infrahub.yml` entries; the template and `device_config`
are unchanged. No twin was booted and no token was printed.

- **Before** (23:28Z–23:29Z). `make build`, then the worker and the server stopped with
  `pkill -x fylgja` and started with `CLAUDE.md`'s two lines (23:28:19Z), and verified: each
  `exe` current, each environment carrying `INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT` and
  `FYLGJA_API_TOKEN`; the two listen lines, the bridge's followed by its unencrypted line; both
  packages with their logins set; from each task worker `200 1 0.1.0-dev`, and `401` without
  the token. `free -m` read 17,760 MiB available, load average 1.5; the dev server was up.
  Infrahub's `main`, read-only: the registration `fylgja` `ref main`, `in-sync`, `online` at
  `5207aae`; 0 check definitions; the query `device_config` alone; `main` and
  `fylgja-fixture` alone; 0 proposed changes, stages, comments and user validators; the
  schema hash `e43a1cde…`. Prefect (its API at the task manager's address on Compose's
  network) held no flow run pending or running, and the minute sync completed each minute.
- **The import** (23:29:33.99Z). `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on
  `main` answered `ok: true` in 0.3 s. Read every second: `sync_status` `syncing` at +10.7 s,
  the query `fylgja_branch` at +15.4 s, **`fylgja-step` 300 and `fylgja-twin` 4200 at
  +21.4 s**, and the commit `999456e`, `in-sync`, at +24.9 s. Prefect: `Import last commit
  from read only git repository` 23:29:36.8–23:29:59.1, beside an `Import objects`
  23:29:38.5–23:29:58.4. A second `Import last commit` followed at 23:30:02.9–23:30:08.3,
  beside `Pull latest commit on fylgja` 23:30:02.9–23:30:12.7 and three `Import objects`.
  Nothing in this run asked for it, and Prefect names neither a parent run nor an automation
  for it; it began 1.3 s after a minute sync ended, and is not attributed here. Then **both
  task workers' `Fetch git repository fylgja on <worker>` ran 23:30:12.9–23:30:13.9**: 39.9 s
  after the call, and 14.8 s after the first import's flow ended, as §1.5 measured 13 s.
- **After** (23:30:38Z). `CoreCheckDefinition` holds `fylgja-step` (timeout 300,
  `infrahub/checks/fylgja_step.py`, `FylgjaStep`) and `fylgja-twin` (4200,
  `infrahub/checks/fylgja_twin.py`, `FylgjaTwin`), each naming the repository `fylgja` and
  the query `fylgja_branch`. `CoreGraphQLQuery` holds `device_config` and `fylgja_branch`. The
  transform and the artifact definition are `srlinux_device_config` alone, as before, and
  `main`'s hash is still `e43a1cde…`. **`fylgja-fixture`** (`0aba31a5…`) lists no check
  definition and reads the registration at `5207aae`: made before the import, it never runs
  the checks (§1.5), which is harmless and needs no rebase.
- **`TestChecksInsideInfrahub` beside the imported checks** (23:31:11Z–23:35:30Z): **PASS in
  249.9 s**, against 198.7 s alone at T050. The registration `fylgja-test-checks-<pid>`
  imported in 10 s, the branch seeded in 30 s, the draft's pipeline concluded after 78 s, the
  re-run with two marks `success` after 42 s (2,266 characters), the stale mark's `failure`
  after 37 s (5,131). A watcher polling `CoreUserValidator` on `main` every 2 s read the
  host's two checks on the test's draft beside the test-only pair, three times each, with
  the same conclusions and message lengths. **`fylgja-step`** concluded `success` at the
  creation (23:32:57–23:33:27, 30 s), `success` with two marks (14 s) and `failure` with the
  stale mark (17 s). **`fylgja-twin`** concluded the draft's skip, `success`, in 18 s, 8 s
  and 8 s. The server logged six `stage.plan`, two at each run (`rejected`: the branch point's
  `contract.node.missing`, or the stale mark; 8.1–11.4 s), and the test's two `twin.show`;
  no `twin.rehearse`. The draft's user validators appeared 43–54 s after its creation, before
  its pipeline ended at 78 s.
- **A hazard for tier 2 on this host, now that the checks are imported.** Every proposed
  change opened here runs `fylgja-step` and `fylgja-twin` at its creation, and `fylgja-twin`
  reads `is_draft` when it runs (§1.3: the user validators about 48 s after the create).
  `TestRehearseComposedByTheFixtureTool` marks its draft ready (`-ready`, 0.2–0.3 s at T050)
  straight after `-propose`. `-propose`'s wait, `testsupport.AwaitValidators`, ends once every
  validator that exists has completed and an artifact validator is among them; it does not
  wait for the user validators to exist. If the creation's user validators came after that
  wait, `fylgja-twin` would read a ready proposed change and ask the operator's server for
  `twin.rehearse`, booting a twin beside tier 2. The test's guard before `-run-checks user`
  (`internal/server/rehearse_contract_test.go`, lines 389–407) covers a re-run, not the
  creation's run. In this run the user validators came before the pipeline's end, and
  T050's `-propose` waited 148–151 s, but no tier 2 has run beside the imported checks yet.
  Case 9 awaits the draft's checks before its `-ready`, and no other test or case marks a
  proposed change ready. This is for converge to weigh: for example, the test could await
  the creation's user checks before `-ready` whenever `main` holds a definition, as case 9
  does.
- **Left clean** (23:36Z): `clab inspect --all` `{}`, no `local/twin`, no Schedule, no
  workflow running; `main` and `fylgja-fixture` alone; 0 proposed changes, stages, comments
  and user validators; the one registration `fylgja`, at `999456e`, with its two
  definitions; no `fylgja-test-*` registration, definition or query. The test's output, the
  watcher's log and the server's and worker's logs were searched for each token, password,
  secret key and login of eight characters or more by its value, and the test's output and
  the watcher's log for the shorter ones in a password's shape, as the test's `noCredential`
  searches them: no hit.

<a id="57-tier-3-whole-and-narrowed-2026-10-19-2343z-2026-10-20-0121z-t055"></a>
### 5.7 Tier 3, whole and narrowed (2026-10-19, 23:43Z – 2026-10-20, 01:21Z; T055, FR-030, SC-002, SC-006, SC-008, SC-010)

Before the first run (23:42Z) the worker and the server were found on a `(deleted)` binary;
`make build`, both stopped and started with `CLAUDE.md`'s two lines, and verified: each
`exe` current; each environment carrying `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`, both
logins, `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`; the server's two listen lines, the
bridge's followed by its unencrypted line; both packages named with their logins set. The
dev server answered `SERVING`; no Schedule, no lab, no `local/twin`; Infrahub's `main` and
`fylgja-fixture` alone, 0 proposed changes, stages and comments, `fylgja-step` 300 and
`fylgja-twin` 4200 on the registration `fylgja` at `999456e`, `in-sync`. `free -m` read
17,816 MiB available (load average 2.3). Each run was started detached as the prompt gives
it, its output in `local/converge-e2e.out`, kept afterwards as `local/e2e-015-*.out`, with
case 9's outputs copied beside them. Tier 3 found two defects; each was fixed with a tier-1
test and the run repeated.

- **Run 1** (23:43:08Z–23:57:18Z): case 9's preconditions passed in seconds (the checks
  on `main`, the server on `172.17.0.1:7650` answering build `0.1.0-dev`); cases 1–6
  passed; **case 7 failed** at its first record: `twin.json` read `twin_version` `"7"` and
  the script expected `"6"`. 015 moved the record to `7` (T007) and left the four asserts of
  cases 7 and 8 (`scripts/e2e.sh`) at 014's version, which only tier 3 reads. The trap left
  the host clean. **Fixed**: the four asserts read `"7"` and `.rehearsal==null` (a hand
  create's and a step's record name no rehearsal), with the header and comments; and
  `TestE2EScriptExpectsTheRecordsVersion` (`internal/lab/twin_test.go`) holds every
  `.twin_version` the script expects to `lab.TwinVersion`, so the next move fails tier 1.
  No Go code changed, so the worker and the server stayed current.
- **Run 2** (00:00:20Z–00:26:41Z): cases 1–8 passed; case 9's draft was skipped by
  `fylgja-twin` and passed by `fylgja-step`; the ready proposed change's checks concluded in
  113.5 s, the rehearsal `01a156b0…` passing in 78.0 s of the 1,950 s deadline with one
  comment of 2,163 characters. After `bad-port` the checks concluded again in 118.7 s and
  `fylgja-twin` failed as it should (its message 8,788 characters, naming `bad-port`'s push
  on n1, the reproduce commands and `head` not reached), but **case 9 failed** on the
  comments: one, not two. `fylgja-twin` had logged `the comment could not be posted: Text
  attribute length should be less than 4096 characters.` at `INFO` and concluded on the
  status alone, as FR-019 has it. **Infrahub 1.11.2's bound**, read in the image's source
  (`/source/backend/infrahub/core/attribute.py`, `MAX_STRING_LENGTH = 4096` and
  `validate_string_length`): a text attribute is refused when `3 + len(value.encode("utf-8"))
  >= 4096`, a margin under Neo4j's index limit of 8,167 bytes, so a comment's text holds at
  most **4,092 bytes**. The failing report's full markdown was over it: beside the table, the
  drawing, the stages and the reproduce commands, its findings section carries each of four
  rejections with its message (the push's refusal some 270 bytes), and its warnings four
  `artifact.interface.unrepresented` of `n1:ethernet-1/99`, one from the read and one from
  the compile of each of `bad-port` and `head`, some 250 bytes each. **Fixed**
  in `internal/rehearsal/markdown.go`, under US2: `CommentMax` (4,092), and `Markdown`
  renders whole whenever that fits, so no pinned output moved; a longer report names each
  finding by its identifier and object alone, identical ones once with their count, since
  the check's message holds the text; and should that still be too long, whole sections
  are left out by rank (the baseline's findings first, then the drawing, the warnings, the
  stages, the findings, the reproduce commands and the table), never inside a fence. The
  heading, the run line and the caveat are always kept, and a line before the caveat says
  what was shortened. `TestMarkdownFitsAComment` pins a report shaped as this one (its full
  rendering over the bound, the shortened one under it with every section, `push.refused
  n1 (×2)` and the warnings `(×4)`, and no message), and fourteen and sixty added stages
  (the table kept, then left out). `contracts/cli.md` and `contracts/rehearse-command.md`
  say so. `make test` passed (43.5 s); `make build`; the worker and the server restarted
  from it (00:33:48Z) and verified as before.
- **Run 3** (00:34:55Z–01:01:54Z): **`E2E-OK`, wall time 1,619.1 s**, nine cases and nine
  twins, against 1,198.9 s at 014 with eight cases and quickstart §7's estimate of 25
  minutes. Case 9 (`fylgja-test-e2e-rh-3724627-8717`): seed 21.5 s; the draft
  `18e016df…` opened in 53.5 s, its checks concluded 0.1 s after `-propose`'s wait; the
  ready proposed change's checks with the rehearsal 109.0 s, **the rehearsal `01a156d0…`
  72.4 s of the 1,950 s deadline**, one comment of 2,176 bytes with the table, the drawing
  and the stages; after `bad-port`, 113.9 s, **the rehearsal `01a156d2…` failing at
  `bad-port`'s push on n1 in 77.1 s of the 2,580 s deadline**, the second comment 3,320
  bytes: shortened, every section kept, the four findings and the warning `(×4)` by
  identifier and object, the reproduce commands and `head` `not reached`. Both well under
  SC-006's fifteen minutes. The other cases' creates took 40.3–93.9 s, and verify 2.9–4.5 s.
- **Narrowed** (01:03:53Z–01:21:01Z), after the host rested to a load average of 1.4:
  `PLATFORMS=nokia_srlinux make test-e2e` ended **`E2E-PARTIAL: platforms nokia_srlinux;
  ran 1 2 3 4 5 7 9; skipped 6 (needs arista_eos: not in PLATFORMS) 8 (needs arista_eos:
  not in PLATFORMS)`**, exit 0, **wall time 1,027.7 s**, against 665.7 s at 014. Case 9's
  checks with the rehearsals 103.3 s (70.3 s of 1,950 s) and 104.0 s (71.2 s of 2,580 s),
  the comments 2,193 and 3,345 bytes.
- **After each run**: `clab inspect --all` found no container, no `local/twin`, no
  Schedule; `Branch` listed `main` and `fylgja-fixture` alone, with 0 proposed changes,
  stages, comments and user validators. The script's credential and marker greps, which
  cover the comments and the checks' messages, passed in runs 3 and narrowed. Every kept
  output, `local/server.log` and `local/worker.log` were searched besides for each token,
  password and secret key of eight characters or more by its value: no hit.

<a id="58-the-walk-through-by-hand-2026-10-20-0121z0127z-t056"></a>
### 5.8 The walk-through by hand (2026-10-20, 01:21Z–01:27Z; T056, SC-012)

`README.md`'s "A proposed change, rehearsed", followed on this host with the worker and the
server from this tree (restarted at 00:33:48Z, unchanged since), the client's commands
with `local/.env` loaded. Outputs in `local/t056/`.

- `-delete`: the branch was absent, so the tool exited 1 (`Branch: fylgja-test-readme not
  found`); the README's line stands for a reader who comes from the stepping section, whose
  branch it deletes. Seed: 23.2 s, its two lines. `-propose`: 53.6 s, `proposed change
  18e01843-9cb0-c335-33b3-c51c6053f556 opened on fylgja-test-readme, draft; 5 validators
  concluded in 53s`.
- The draft's checks, read through the API: `fylgja-twin` `success` in 7.5 s, its message
  the skip naming the id; `fylgja-step` `success` in 18.3 s, its message (1,038
  characters) the plan of the two stages, the branch point refused `contract.node.missing`,
  the head's bundle `e26a0e65…`, then the finding. No comment.
- `-stage seeded` at `01:23:39.142559`; `-add-link`, n1's and n3's checksums moved and
  `Ready` 7.2 s after it returned; `-stage third-link` at `01:23:48.370039`; `-ready`.
  `-run-checks user` in place of the view's button: 103.6 s, `check fylgja-step: success
  (message 2,027 characters)`, `check fylgja-twin: success (message 3,693 characters)`.
  `fylgja-step` took 13.6 s and `fylgja-twin` 87.8 s, its rehearsal `01a156e8-da76-…`
  70.7 s of the 1,950 s deadline. One comment, `18e01873…`, 1,955 bytes, rendered whole:
  the heading, the run line, four rows, the drawing, the four stages, no warnings, no
  baseline findings, the caveat.
- `bin/fylgja twin rehearse --branch fylgja-test-readme`: exit 0 in 83.1 s, `rehearsal ok:
  3 stages rehearsed, every one passed; the twin is destroyed; 72.1s of the 1950s
  deadline`, the deadline `32m30s` as the README had it; still one comment afterwards, since
  Fylgja writes nothing to Infrahub.
- **The README corrected** to these outputs: the seed's lines and the ids; the draft's two
  checks with their times and `fylgja-step`'s whole message; the checksums' 7 seconds;
  `fylgja-twin`'s time against the rehearsal's; `-run-checks`' message lengths; the comment
  whole; `twin rehearse`'s lines, ids and times; the comment's bound (§5.7); and tier 3's
  time, about 27 minutes (the narrowed run's 17 stood).
- **Left for T057**, as the task says: the branch `fylgja-test-readme`, its proposed change
  (ready for review, so a re-run of its checks would rehearse it and boot a twin), its two
  stages, its one comment and its two user validators. Nothing else: no lab, no
  `local/twin`, no Schedule, `main` and `fylgja-fixture` beside it. The outputs hold no
  credential (§5.7's search).

### 5.9 The comment in Infrahub's view, and why it was not there (2026-10-20, 17:55Z–18:15Z; T057, US2)

**The operator's reading**, in a browser, of what T056 left (`tasks.md`, T057): the
proposed change's overview showed **no comment**, although Infrahub held one; both checks'
messages showed under the checks tab, as plain text with their line breaks kept, three
messages each at `Level: INFO`: the check's own, the findings line, and Infrahub's `Check
succesfully completed` (its spelling). The messages are as §1.2 read them and D-049 chose:
nothing there is Fylgja's to fix.

**Why**, read from 1.11.2's source in the image (`/source/frontend/app/src`,
`/source/backend/infrahub`) and verified against the running instance:

- The overview (`entities/proposed-changes/ui/overview.tsx`) is the proposed change's
  **events** and an *Add comment* form. The events are `InfrahubEvent` filtered to the
  proposed change as primary node and to the types `PROPOSED_CHANGE_EVENTS` names. The one
  of them that shows a comment is `infrahub.proposed_change_thread.created`: its card reads
  "<account> created a thread" and shows the thread its first related node names, with that
  thread's `CoreThreadComment`s (`GetCoreThread`), each through `MarkdownRender`
  (`remark-gfm`, `remark-breaks`, and Mermaid when a ```` ```mermaid ```` fence is present).
  `infrahub.proposed_change.comment` is listed too, but nothing in the backend emits it.
- The view's *Add comment* writes a `CoreChangeThread` (`change` the proposed change,
  `label` `Conversation`, `resolved` false), then a `CoreThreadComment` (`text`, `thread`
  that thread), and deletes the thread when the comment fails.
- The backend (`events/generator.py`) emits `ProposedChangeThreadCreatedEvent` when a
  `CoreChangeThread`, `CoreObjectThread`, `CoreArtifactThread` or `CoreFileThread` whose
  `change` is a proposed change is created. A `CoreChangeComment` emits only
  `infrahub.node.created`, with the comment as primary node. `CoreProposedChange.
  total_comments` counts both kinds (`core/node/proposed_change.py`); no file of the
  frontend reads `CoreChangeComment` but the generated types and the menu.
- Live, on `18e01843-9cb0-c335-33b3-c51c6053f556` (`local/t057/`), before anything was
  changed: one `CoreChangeComment`, `18e01873-9d1b-5f84-33bf-c51ebe0c3754`, 1,954 bytes of
  UTF-8 text; no thread; `total_comments` 1. The overview's own query answered **0
  events**; the proposed change's events were its `infrahub.node.created` and seven
  `infrahub.node.updated`; the comment's one event was `infrahub.node.created` on `main`,
  primary node the `CoreChangeComment`, related node the proposed change.

So the defect is the kind D-049 named, not the markdown: §1.3 verified that a check may
create a `CoreChangeComment`, and §1.2 read the rendering of a comment from the frontend's
source, but neither read which comments the overview lists (§1.8 left the rendering for
T057). The schema in the image declares `CoreProposedChange.threads` and
`CoreThread.comments` as components with `on_delete: cascade`, as `comments` is.

**The fix, Fylgja's to fix under US2**: `post_comment` (`infrahub/checks/fylgja_api.py`)
posts the report as the view writes a comment: a `CoreChangeThread` on the proposed change,
labelled `Conversation` and unresolved, then one `CoreThreadComment` in it with the report's
markdown as its text, both on `main`; a thread whose comment cannot be saved is deleted, as
the view deletes its own. The text's bound, `rehearsal.CommentMax`, holds unchanged: the
thread's comment is a `CoreComment` whose `text` is the same `TextArea`. This supersedes
D-049 in the kind it names, drafted below as D-053 for the operator.

- **By hand** (18:00:10Z–18:00:30Z): the tree's `post_comment`, run from `.venv` with the
  SDK as `INFRAHUB_API_TOKEN`'s account, on `18e01843…`, with the `CoreChangeComment`'s text:
  `posted` in 6.3 s. The proposed change then held thread
  `18e04eba-0463-9706-33b8-c51290b7b2fe` (`CoreChangeThread`, `Conversation`, unresolved)
  with one comment, `18e04eba-a220-…`, byte for byte the report; `total_comments` 2. The
  overview's own query answered **1 event**: `infrahub.proposed_change_thread.created` on
  `main` at `18:00:14.678345Z`, primary node the proposed change, related node the thread,
  read within 16 s of the post.
- **`-delete`** (18:01Z), as the operator asked once the cause was found: `deleted 2 stages,
  1 proposed change, branch fylgja-test-readme` in 14.3 s. Twenty seconds later
  `CoreProposedChange`, `FylgjaStage`, `CoreChangeComment`, `CoreChangeThread`,
  `CoreThreadComment`, `CoreUserValidator` and `CoreStandardCheck` each counted 0, and
  `Branch` listed `main` and `fylgja-fixture` alone: **a proposed change's delete takes its
  threads and their comments with it**, verified.
- **The test** (tier 2, `internal/checks`' `TestChecksInsideInfrahub`, the tree's checks in
  Infrahub's pipeline through the test's registration, R-18): a new step 7 marks the draft
  ready with the stale mark standing and re-runs the user checks. Fylgja refuses the
  rehearsal before any boot (the spec's edge case "A stage refused on the way in"), and
  `fylgja-test-twin` must conclude failure naming `stage.artifact.stale` and post the report
  (US2/AC3) as the overview shows it: each comment alone in its thread, `Status
  **rejected**` and the rule in its text, and every thread named by a
  `infrahub.proposed_change_thread.created` event of the proposed change within a minute.
  Test support's `CommentsOf` now reads the comments of the proposed change's threads, and
  `OverviewThreads` reads its events as the view does. The host's own registration's
  `fylgja-twin` runs beside the test's and may post the same report, so the test asks for at
  least one comment. **Passed** in 309.4 s (18:04Z–18:09Z): `fylgja-test-twin` concluded
  failure after 31 s, message 3,873 characters, one comment posted in a thread the overview
  lists; no twin. With the old `post_comment` swapped into the test's registration, the
  same test **failed** at the comment, in 219.7 s (18:09Z–18:13Z): `fylgja-test-twin` concluded failure after 27 s as before, and then `the proposed change …, marked ready, holds no comment its overview shows`.
- **Tier 3's case 9** reads the threads' comments too (`comments_of` in `scripts/e2e.sh`),
  each rehearsal's comment alone in its own thread, and after `-delete` counts the threads
  and their comments. It runs the checks the host's registration imported from `origin`'s
  `main`, which still post a `CoreChangeComment`: **case 9 passes only once this fix is
  pushed and imported** (R-21), so tier 3 was not run here.

**Still owed (T057 stays open)**: the reading itself. No one has yet seen the report in the
overview: the table, the Mermaid drawing (no error banner), the stages and the caveat, in a
thread. It needs the fix on `origin`'s `main` and imported on the host's registration (the
operator's push and import, R-21), then a proposed change rehearsed through the check (the
README's walk-through), then the operator's reading. `remark-breaks` renders each single
line break of the markdown as a break, which the reading should look at. Then `-delete`.

**Records owed** (Run 21): `docs/verified-facts.md` gains that 1.11.2's proposed-change
overview lists a comment only in a thread, through the event a thread's creation emits, a
`CoreChangeComment` being counted and never shown, and that a proposed change's delete
takes its threads and their comments; `docs/architecture.md` §4.6 says the check posts a
thread. Once D-053 is accepted, `spec.md`'s FR-019 ("no object") and SC-007 ("one new
comment"), and `plan.md`'s lines 81 and 160, which name `CoreChangeComment`, are the
operator's to amend, as T081 amended 014's.

> **D-053 — The check's comment is a thread on the proposed change, as its view shows
> one.** Supersedes [D-049](../../docs/decisions.md#d-049) in the kind it names; D-049's
> checks as clients of the API and glue, one new comment per run carrying the report's
> markdown headed by the run, none edited, `fylgja-step` writing nothing, a comment that
> cannot be posted failing nothing, and [D-026](../../docs/decisions.md#d-026) stand.
> Context: D-049 named `CoreChangeComment`, which §1.3 verified a check may create, and the
> reviewer reads the report in the proposed change's view (US2). Verified on 1.11.2
> (2026-10-20, §5.9): the overview lists the proposed change's events, and a comment
> appears there only in a thread, through the event a thread's creation emits; a
> `CoreChangeComment` is counted in `total_comments` and shown nowhere in the view; the
> operator read no comment in the overview of a proposed change that held one. Options:
> keep `CoreChangeComment` (rejected: no reviewer sees it); an object or artifact thread
> (rejected: each is anchored to an object or an artifact's line, and the report is the
> whole proposed change's); a `CoreChangeThread` holding one `CoreThreadComment`, as the
> view's own *Add comment* writes one (chosen). Decision: `fylgja-twin` posts each run's
> report as one new `CoreChangeThread` on the proposed change, labelled `Conversation` and
> unresolved as the view labels its own, holding one `CoreThreadComment` whose text is the
> report's markdown, both on `main`; it deletes the thread it made when the comment cannot
> be saved, as the view does, and otherwise edits and deletes nothing and writes nothing
> else. Consequences: each rehearsal is a thread in the proposed change's overview, in the
> order run; a reviewer may reply to it or resolve it, which nothing of Fylgja's reads; a
> test's proposed change goes with its threads and their comments when deleted (§5.9).

<a id="510-the-thread-imported-tier-3-and-the-walk-through-again-2026-10-20-1823z1926z-t057"></a>
### 5.10 The thread imported, tier 3, the walk-through again and the reading (2026-10-20, 18:23Z–19:55Z; T057)

The operator pushed the fix and D-053 to `origin`'s `main` (`999456e` → `d70ad24`, T057's
note), and this run, the loop's Run 20 restarted, imported it, ran tier 3 whole and
narrowed with case 9 reading threads, and followed the README's walk-through again to leave
a fresh proposed change for the operator's reading; once the operator had read it, the run
deleted it. Outputs in `local/t057-2/`, `local/t057-3/`, `local/e2e-015-full-4.*` and
`local/e2e-015-srl-2.*`. No token or password was printed.

- **Before** (18:23Z). The worker and the server were on a `(deleted)` binary: `make build`,
  both stopped with `pkill -x fylgja` and started with `CLAUDE.md`'s two lines (18:23:28Z),
  and verified: each `exe` current; each environment carrying `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN`, both logins, `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`; the two
  listen lines, the bridge's followed by its unencrypted line; both packages with their
  logins set. The dev server answered `SERVING`; no lab, no `local/twin`, no Schedule, no
  workflow running. Infrahub's `main`: the registration `fylgja` `ref main`, `in-sync`,
  `online` at `999456e`, with `fylgja-step` 300 and `fylgja-twin` 4200; `main` and
  `fylgja-fixture` alone; 0 proposed changes, stages, threads, comments of either kind and
  user validators. Prefect held no flow run pending or running.
- **The import** (18:24:12.85Z). `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on
  `main` answered `ok: true`; `syncing` at +3.9 s, **`d70ad24`, `in-sync`, at +7.3 s**.
  Prefect: `Import last commit from read only git repository` 18:24:14.3–18:24:19.8 beside
  an `Import objects`; a second `Import last commit` 18:24:21.2–18:24:24.6 beside `Pull
  latest commit on fylgja` 18:24:21.2–18:24:29.2 and three `Import objects`, as at §5.6 and
  as unattributed; then **both task workers' `Fetch git repository fylgja` 18:24:29.4–
  18:24:30.8**, 16.6 s after the call. Afterwards the two definitions, both naming the
  repository `fylgja` and the query `fylgja_branch`, the queries `device_config` and
  `fylgja_branch`, the transform and artifact definition `srlinux_device_config`, and
  `main`'s hash `e43a1cde…`, each as before. Each task worker holds the commit's worktree
  `commits/d70ad24…`, whose `fylgja_api.py` writes a `CoreChangeThread`; task-worker-2's
  `main` worktree reads `d70ad24` and task-worker-1's still `9cba3c9`. Every `fylgja-twin`
  run below posted a thread and no `CoreChangeComment`.
- **Tier 3 whole** (18:25:01Z–18:50:38Z; `free -m` 17,748 MiB available, load average
  1.8): **`E2E-OK`, wall time 1,536.9 s**, nine cases and nine twins. Case 9
  (`fylgja-test-e2e-rh-2192569-17413`): seed 36.8 s; the draft `18e05132…` opened in 54.3 s,
  its checks concluded 0.9 s after; the ready proposed change's checks with the rehearsal
  103.4 s, the rehearsal `01a15aa3…` passing in 68.4 s of the 1,950 s deadline, **one comment
  of 2,192 bytes alone in thread `18e05159-7762…`**; after `bad-port` 115.9 s, the rehearsal
  `01a15aa5…` failing at `bad-port`'s push on n1 in 77.7 s of the 2,580 s deadline, **a second
  comment of 3,344 bytes in a second thread, `18e05177-6351…`**; after `-delete`, both
  threads, both comments and the user validators counted 0. Verify took 3.3–4.5 s.
- **Narrowed** (18:55:29Z–19:12:52Z), after the host rested to a load average of 0.8:
  `PLATFORMS=nokia_srlinux make test-e2e` ended **`E2E-PARTIAL: platforms nokia_srlinux;
  ran 1 2 3 4 5 7 9; skipped 6 (needs arista_eos: not in PLATFORMS) 8 (needs arista_eos:
  not in PLATFORMS)`**, exit 0, **wall time 1,042.9 s**. Case 9: checks with the rehearsals
  109.0 s (68.9 s of 1,950 s) and 114.0 s (73.9 s of 2,580 s), the comments 2,192 and 3,344
  bytes, each in its own thread, both gone after `-delete`.
- **After each run**: `clab inspect --all` `{}`, no `local/twin`, no Schedule; `main` and
  `fylgja-fixture` alone, with 0 proposed changes, stages, threads, comments of either kind
  and user validators. The script's credential and marker greps, which cover the comments
  and the checks' messages, passed in both runs.
- **The walk-through** (19:20:16Z–19:25:42Z), `README.md`'s "A proposed change, rehearsed",
  after the host rested to a load average of 1.2, with the client's commands from a shell
  that had loaded `local/.env`. `-delete`: the branch was absent, exit 1, as at §5.8. Seed
  16.7 s. `-propose` 56.0 s: `proposed change 18e0531d-0848-4684-33b7-c511bd30ba49 opened on
  fylgja-test-readme, draft; 5 validators concluded in 55s`. The draft's checks:
  `fylgja-twin` `success` in 10.3 s, its message the skip naming the id; `fylgja-step`
  `success` in 17.9 s, its message 1,038 characters as at §5.8, the head's bundle
  `2af3936f…`; no thread. `-stage seeded` at `19:21:55.635779`; `-add-link`, n1's and n3's
  checksums moved and `Ready` within 9.3 s of its return; `-stage third-link` at
  `19:22:07.489787`; `-ready`. `-run-checks user`: 98.0 s, `check fylgja-step: success
  (message 2,027 characters)`, `check fylgja-twin: success (message 3,693 characters)`, the
  same lengths as §5.8's. `fylgja-step` took 11.6 s and `fylgja-twin` 84.0 s, its rehearsal
  `01a15ac3-fd7f-…` 70.7 s of the 1,950 s deadline. **One thread,
  `18e0534a-1076-c85e-33b1-c5167c56a2b6`** (`CoreChangeThread`, `Conversation`, unresolved),
  holding **one `CoreThreadComment`, `18e0534a-148b-36af-33b0-c51852e3803f`, 1,954 bytes**,
  rendered whole: the heading, the run line, four rows, the drawing, the four stages, no
  warnings, no baseline findings, the caveat. `total_comments` 1, no `CoreChangeComment`.
  The proposed change's events end with the thread's `infrahub.node.updated` and **its
  `infrahub.proposed_change_thread.created` at `19:23:49.295577Z`**, the one event by which
  the overview lists a thread, naming `18e0534a-1076-…`. `bin/fylgja twin rehearse --branch
  fylgja-test-readme`: exit 0 in 78.7 s, `rehearsal ok: 3 stages rehearsed, every one
  passed; the twin is destroyed; 68.3s of the 1950s deadline`, the deadline `32m30s`; still
  one thread and one comment afterwards. The README's outputs stand, within these runs'
  spread; three of its sentences named a plain comment and now name the thread (D-053), and
  `docs/decisions.md` gains D-053's anchor, which D-049's status and `spec.md` link to.
- **Left for the operator's reading**, as T057's note asks, against the run's general "no
  `fylgja-test-*` branch": the branch `fylgja-test-readme`, its proposed change
  `18e0531d-0848-4684-33b7-c511bd30ba49` (open and ready for review, so a re-run of its
  checks would rehearse it and boot a twin), its two stages, its one thread with its one
  comment, and its two user validators. Nothing else: no lab, no `local/twin`, no Schedule,
  `main` and `fylgja-fixture` beside it. The kept outputs, `local/t057-2/`,
  `local/server.log` and `local/worker.log` were searched for each token, password and
  secret key of eight characters or more by its value: no hit.

**The reading** (the operator, in a browser, at about 19:47Z by the screenshot's "24
minutes ago"; T057's note): "Looks good", with a screenshot of the overview of
`18e0531d-0848-4684-33b7-c511bd30ba49`. It shows the event `Agent created a thread`; the
thread, labelled `Conversation`, authored `Agent` (the account the task worker's check
writes as), with `Resolve thread` and `Reply`; and in it the report whole, as its markdown
gives it. The heading. The run line: the run's id in code, its status **ok** in bold, 70.7 s
of the 1,950 s deadline, the ceiling 3,600 s. The table: eight columns and four rows (the
branch point refused `contract.node.missing`, `seeded` the baseline, `third-link` and the
head passed), each bundle id cut to eight characters, long cells wrapping. The Mermaid
drawing with its zoom controls and **no error banner**: four boxes whose `<br/>` show as
line breaks, the dotted `not computed` edge, the step's edge labelled `+link n1:e1-3 —
n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3`, and the `unchanged` edge.
**Stages** ("Infrahub's view does not show them") as a list of four, each stage in code;
**Warnings** none; **Baseline findings** none; the caveat in italics. Nothing was seen
broken, `remark-breaks` included, so nothing is Fylgja's to fix:
`internal/rehearsal/markdown.go` and its tests are unchanged. With §5.9's reading of both
checks' messages under the checks tab, §4's "the comment's table and Mermaid and a long
message looked at in the UI" is done.

- **`-delete`** (19:54:15Z), from this tree, the worker and the server first rebuilt and
  restarted (both had read `(deleted)`) and verified as `CLAUDE.md` asks. Read through the
  API at 19:54:02Z, what the walk-through left was unchanged: the branch, its proposed
  change open and not a draft with `total_comments` 1, the stages `seeded` and
  `third-link`, the thread `18e0534a-1076-…` (`Conversation`, unresolved) holding one
  `CoreThreadComment` byte for byte `local/t057-2/11-comment.md` but for that file's closing
  newline, no `CoreChangeComment`, and the two user validators `completed`, `success`.
  Then `deleted 2 stages, 1 proposed change, branch fylgja-test-readme`, exit 0 in 7.2 s.
- **After** (19:54:47Z): `Branch` lists `main` and `fylgja-fixture` alone, and
  `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread`, `CoreThreadComment`,
  `CoreChangeComment`, `CoreUserValidator` and `CoreStandardCheck` each count 0, as at §5.9's
  `-delete`; `clab inspect --all` is `{}`, with no `local/twin`, no Schedule and no workflow
  running. T057 is done.

### 5.11 Convergence pass 1: tier 2 beside the imported checks, and the edge case settled (2026-10-20, 20:47Z–21:17Z; T065, T066)

The loop's run of convergence pass 1's tasks, unattended: Infrahub's address and token and
the API's token in its environment, no node login, no twin booted, the worker and the
server left as they ran. Outputs in this session's scratchpad. No token was printed.

- **The `-ready` that did not await the creation's checks** (§5.6's hazard).
  `testsupport.AwaitUserChecks(id, timeout)` sends nothing: it reads the check definitions
  of a registered repository the source branch sees, as `RunUserChecks` does, and polls the
  user validators every 5 s until each definition has one reading `completed`; it returns
  at once when the branch sees none, and at the bound names each `not started` or in its
  state. `TestRehearseComposedByTheFixtureTool` calls it between `-propose` and `-ready`,
  bounded at 6 minutes as `internal/checks` bounds a creation's checks; the code under test
  is unchanged. Alone (20:47:51Z–20:49:50Z) it **passed in 113.7 s**: the seed 22 s,
  `-propose` 62.7 s (`5 validators concluded in 63s`), and the host's `fylgja-step` and
  `fylgja-twin` already `completed` on the draft 1 s into the wait, before `-ready`. The
  server logged the creation's `stage.plan` (`rejected`, the branch point's
  `contract.node.missing`, 7.0 s) and no `twin.rehearse`. Here, as at §5.6, the user
  validators concluded inside `-propose`'s own wait; the new one holds `-ready` back when
  they do not.
- **The server on the bridge** (20:47:42Z), with no twin, by quickstart §2's request from
  inside both task workers: `200`, `Fylgja-Api-Version` `1`, `Fylgja-Build` `0.1.0-dev`, a
  240-byte answer, with the container's token, and `401` without it; `401` from the host
  without one. The server and the worker read `(deleted)`: both were started at 20:28:35Z
  by Run 23, and `bin/fylgja` was relinked at 20:30 with no Go source changed since. A loop
  session holds no node login, so neither was restarted.
- **Tier 2 whole** (20:56:01Z–21:16:21Z; `free -m` 17,638 MiB available, load average 4.1):
  **PASS, wall time 1,220.1 s**, against 1,099.7 s at §5.5, under the `-timeout 30m`. The
  first `go test` took about 965 s: `internal/stages` 960.4 s, `internal/stage` 657.2 s,
  `internal/server` 651.6 s (`TestRehearseComposedByTheFixtureTool` with the wait among it)
  and `internal/intent` 247.7 s. Then `internal/checks` alone took 252.8 s and reached its
  seventh step, since the task workers reach the server. Every proposed change the tier
  opened ran the host's two checks at its creation, as §5.6 foresaw: the server logged
  thirteen `stage.plan` from 21:00:28Z to 21:16:04Z, each `rejected` (the branch point's
  `contract.node.missing`, or `internal/checks`' stale mark), five of them while the first
  `go test` ran. It logged two `twin.rehearse`, at 21:16:04Z and 21:16:06Z:
  `internal/checks`' ready proposed change, asked for by its `fylgja-test-twin` and by the
  host's `fylgja-twin`, each `rejected` before any boot (7.4 s and 6.9 s). No twin was
  booted. Tier 1 had run just before it, hence the load average.
- **After**: `twin show` printed `twin: none: no lab fylgja, no twin directory` and `in
  flight: none`; `clab inspect --all` read `{}`, with no `local/twin`, no running workflow
  and no Schedule. Quickstart §5's query, widened: `Branch` lists `main` and
  `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread`,
  `CoreThreadComment`, `CoreChangeComment`, `CoreUserValidator` and `CoreStandardCheck`
  each count 0; `CoreReadOnlyRepository` holds `fylgja` alone, at `d70ad24`, with
  `fylgja-step` (300) and `fylgja-twin` (4200); `CoreGraphQLQuery` holds `device_config`
  and `fylgja_branch`. No `fylgja-test-*` branch, registration, definition or query is
  left. The tier's and the test's outputs, this session's task outputs and
  `local/server.log` were searched for each token, password and secret key by its value: no
  hit.
- **A source branch deleted under a running rehearsal** (T066). The operator answered the
  loop's question 3 with (a): the spec's edge case was amended to what runs (`824604f`).
  What runs reads nothing of Infrahub during the run: every stage is resolved, compiled and
  filed before the start (FR-003), and the children step from the store's bundles. A branch
  deleted under it changes nothing of the run, which finishes on the stages it compiled and
  runs its destroy. The one read after the run, `after` in `internal/server/rehearse.go`,
  warns `rehearsal.stage.moved` naming the branch when the stages cannot be read again, or
  `rehearsal.change.closed` once Infrahub has cancelled the proposed change, about 16 s
  after its branch's delete (`docs/verified-facts.md`); the status stays the stages', as
  FR-011 says of a moved stage. R-08's table, `contracts/rehearse-command.md` and
  `contracts/cli.md` already said so. Nothing was built.
