# Contract: the two checks, `fylgja-step` and `fylgja-twin`; 020's reach through the orchestrator's platform

Infrahub's runtime, as the Jinja template is: Python glue in this repository, run by
Infrahub's task workers on a proposed change at its creation and on a re-run, reaching
Fylgja through the orchestrator's platform alone (020's FR-024, R-12). Everything that
decides is the orchestrator's flows' and the core's; the Python finds the proposed change,
triggers one flow, waits for its run, reads the run's document and out lines, and concludes.
Neither check writes to Infrahub: the rehearse flow posts the report itself
([D-065](../docs/decisions.md#d-065); 020's R-11).

Moved here from [015's](../specs/015-proposed-change-rehearsal/contracts/checks.md), which
reached the core's API (`POST /v1/stage/plan`, `POST /v1/twin/rehearse`) with its token, and
whose `fylgja-twin` posted the report. The conclusions, the retry while the host is held
and the margins are 015's, unmoved.

## Registration (`.infrahub.yml`)

```yaml
queries:
  - name: device_config
    file_path: infrahub/queries/device_config.gql
  - name: fylgja_branch
    file_path: infrahub/queries/branch.gql           # { Branch { name } }: the cheap read the SDK requires of a check

check_definitions:
  - name: fylgja-step
    file_path: infrahub/checks/fylgja_step.py
    class_name: FylgjaStep
  - name: fylgja-twin
    file_path: infrahub/checks/fylgja_twin.py
    class_name: FylgjaTwin
```

Global (no `targets`, no `parameters`); the query is the class's `query = "fylgja_branch"`,
never a `query:` key under the definition. `infrahub/checks/fylgja_api.py` is the shared
glue, imported relatively (`from .fylgja_api import …`), which Infrahub's module naming
allows (015's research §1.2). The definitions reach Infrahub as the template does: on
`origin`'s `main`, imported on request ([D-044](../docs/decisions.md#d-044)); a branch
created before the import does not run them until rebased or recreated (015's research
§1.5).

## The environment, and what each check needs

| Variable | From | Unset |
|---|---|---|
| `FYLGJA_ORCHESTRATOR_ADDRESS` | the override: `host.docker.internal:4200`, the platform on the bridge | `log_error` naming the variable, nothing sent, conclusion failure; `fylgja-twin` on a draft reads neither variable and skips it |
| `FYLGJA_ORCHESTRATOR_AUTH` | the override, from `local/.env`: `<user>:<password>`, the platform's basic auth | the same; a value with no `:`, or with a character a header cannot carry, is refused the same way |

Nothing else of Fylgja's, Infrahub's or a node's: never the core's `FYLGJA_API_TOKEN`
(FR-024). The check's own client (`self.client`, the task worker's) is used for one read and
nothing more: the proposed change by `source_branch__value = branch_name` and `state__value
= open` (its `id`, `name`, `is_draft`). No credential and no configuration line reaches a
message or a log line, and of the two variables' values only the address does, which a fault
names as the platform it tried. The glue is stdlib and `httpx` alone, as the task worker's
image carries them, and never Prefect's client, whose environment there points at
Infrahub's own Prefect server (020's research §1.1).

## The platform's API the glue asks (Prefect 3.8.8; 020's research §1.3, §1.4, §5.21)

Every request goes to `http://<FYLGJA_ORCHESTRATOR_ADDRESS>/api` (or the `http://` or
`https://` URL the variable names) with basic auth, no proxy of the environment's and no
redirect followed; each is bounded by 5 s to connect and 30 s to answer.

| Glue | Request | Read |
|---|---|---|
| `trigger(flow, parameters)` | `GET /api/deployments/name/<flow>/main`, then `POST /api/deployments/<id>/create_flow_run` `{"parameters": {"branch": <branch_name>}}` | the deployment's `id`, then the run's `id`; a `503` to either is asked once more after 5 s; a `404` to the first is a deployment the runner does not serve |
| `wait(flow_run_id, deadline)` | `GET /api/flow_runs/<id>` every 5 s | `state.type`, `state.name`, `state.message`, to `COMPLETED`, `FAILED`, `CANCELLED` or `CRASHED`, or the last read at the deadline; a read that cannot reach the platform is asked again at the next poll |
| `document(flow_run_id)` | `POST /api/artifacts/filter` `{"artifacts": {"flow_run_id": {"any_": [<id>]}, "type": {"any_": ["fylgja-findings"]}}, "sort": "CREATED_DESC", "limit": 1}` | the artifact's `data`, a JSON string, parsed as the findings document; none when the run filed none |
| `lines(flow_run_id)` | `POST /api/logs/filter` `{"logs": {"flow_run_id": {"any_": [<id>]}}, "sort": "TIMESTAMP_ASC", "limit": 200, "offset": …}`, paged | the `message` of each record whose `name` is `prefect.flow_runs.fylgja`, the flow's out lines, apart from Prefect's own lines; read until two reads 1 s apart agree, at most five, since the log lands about a second after the state |
| `cancel(flow_run_id)` | `POST /api/flow_runs/<id>/set_state` `{"state": {"type": "CANCELLING"}}`, blocking, bounded by 10 s | `ACCEPT` (a running run), `REJECT` (a scheduled one, cancelled at once) and `ABORT` (one already ended) are each delivered; **no `force`**, which would move a run that has just ended out of its end |

A `401` to any request is the platform refusing the credential, named by its variable.

## `fylgja-step` (`timeout = 300`)

1. The variables; the proposed change (none open on the branch: `log_error`).
2. Trigger `stage-plan` with `{"branch": <branch_name>}`, and wait for its run, but no
   later than the check's own deadline, 120 s before its `timeout` (180 s after it began;
   `CLOSE_MARGIN_S`, shared with `fylgja-twin`): past it the run is asked to cancel.
3. Once the run has ended, `log_info` the run's identity (`flow run <id> of
   stage-plan/main: <state>`) and its out lines, the plan's text, in one entry; then the
   findings' text, as WriteText prints them, each line, then the summary.
4. **Conclusion**: `log_error` when the document's findings hold a rejection, **except** a
   branch point (`at_source: branch_point`) whose one rejection is `scope.empty` at `read`
   (017's FR-015); when the plan's status is `error` or any status but `ok` and `rejected`;
   when the run filed no document (`flow run <id> of stage-plan/main: <state>, and it filed
   no document`); and when the platform cannot be reached, refuses the credential, serves no
   `stage-plan/main` or cannot be read once the run exists, naming the address and never the
   credential; and when the plan has not ended by the check's own deadline: `the stage plan
   did not answer by this check's own deadline, 180 s after it began (<the run and its
   state>), and it was asked to cancel: nothing was started, and a re-run of the checks asks
   again`, rather than Infrahub's timeout leaving the validator `in_progress` (FR-021). A
   plan whose every other stage compiled passes, `stage.main.moved` and the other warnings
   included.

Runs on every open proposed change, draft or not.

## `fylgja-twin` (`timeout = 4260`)

1. The proposed change (none open on the branch: `log_error`), then the variables. **A
   draft** (`is_draft`) is decided first, since it needs nothing of the orchestrator's
   (FR-020): `log_info` `skipped: proposed change <id> is a draft; mark it ready for review
   and re-run the checks to rehearse it`, conclusion success, neither variable read and
   nothing triggered.
2. Trigger `twin-rehearse` with `{"branch": <branch_name>}` and wait for its run to its
   end, or to the check's own deadline, its `timeout` less 240 s (`DEADLINE_MARGIN_S`;
   4,020 s, the flow's own `timeout_seconds`: the allowance, the ceiling and the destroy).
   Once the run has ended, its identity and out lines are logged in one entry (015's T046).
3. **The host held** (a `rejected` document whose every rejection is `run.in_flight`,
   `host.lab.present` or `host.twin.present`, the branch point's lone `scope.empty` at
   `read` passed over as `fylgja-step` passes it over): the flow touched nothing and posted
   nothing. Wait 30 s and trigger again while what would remain of the check's own deadline
   at the next ask still covers the refused rehearsal's deadline (the block's
   `deadline_s`), the destroy's budget (`DESTROY_S`, 120 s) and the allowance before the
   run's start (`ALLOWANCE_S`, 300 s), so that no run the check starts is cancelled by it
   (FR-007, FR-021); then `log_error` naming the run or the twin the last document named and
   what the remainder does not cover. A retried refusal is logged once while it says the
   same. A run the check asked to cancel is final.
4. **The report** is the flow's: it posts one thread holding the markdown on the proposed
   change, as 015's check did, unless the host is held (020's R-11, research §5.18); the
   check posts nothing and writes nothing.
5. **Conclusion**: the document's `status` alone: `ok` → success; `rejected`, `error`,
   `failed`, `unclean`, `nonconforming` → `log_error` with the findings' text. A run that
   filed no document: `log_error` `flow run <id> of twin-rehearse/main: <state>, and it filed
   no document; <goes on>`. The platform unreachable, refusing the credential or serving no
   `twin-rehearse/main` before the run exists: `log_error` naming the address.
6. **The platform lost once the run exists** (its state cannot be read to the deadline, or
   its document cannot be read once it ended): `log_error` `flow run <id> of
   twin-rehearse/main was triggered, then <the fault>; any run of the core's it started goes
   on to its destroy, and a report it could not file is not posted; re-run the checks once
   fylgja twin show reports no twin`. The run is not cancelled.
7. **The check's own deadline** with the run not ended: the run is asked to cancel; the
   flow, cancelled, interrupts the core's run in progress, destroys and files its document
   and its report within the runner's 30 s grace (020's research §5.18); the check waits on
   to the run's end, but no later than 120 s before its timeout (`CLOSE_MARGIN_S`), then
   concludes from the document with `this check's own deadline, 4020 s after it began,
   passed with flow run <id> of twin-rehearse/main still running: it was asked to cancel`
   first (`, but the cancellation was not delivered: <why>` when it was not). A run still
   not ended then is `log_error` with that sentence, `it had still not ended 120 s before
   this check's timeout (<the run and its state>)` and the sentence of 6. **Cancelled or
   timed out by Infrahub** (`BaseException` in the handler) while the run has not ended: the
   run is asked to cancel with a blocking call, never an `await` (015's research §1.4), and
   the exception re-raised; Infrahub leaves the validator `in_progress`, which blocks the
   merge.

The message is the run's out lines and the document's findings; the report is the flow's
thread; the conclusion is the status's mapping and nothing else
([D-052](../docs/decisions.md#d-052)).

## What Infrahub shows

- The check's message under `Message` in the proposed change's checks tab, as plain text
  with its line breaks kept (015's research §5.9): the run's identity and out lines, then
  the findings.
- The report in the proposed change's overview, as the thread the rehearse flow's post
  lists ("<account> created a thread"), its one comment rendered as markdown
  ([D-053](../docs/decisions.md#d-053), kept in its thread by D-065).
- The validator `Check: fylgja-twin` `success` or `failure`; a failure blocks the merge
  (every validator but the data one must succeed).

## Timings on the development host

On a throwaway Prefect 3.8.8 platform (020's research §5.21), a run is picked up by its
runner and read ended about 6–14 s after `create_flow_run` (the runner's poll), its log a
second later; a cancelled run read `CANCELLED` about 6 s after the request, its document
filed. `fylgja-step` answers in the plan's time plus about 15 s; `fylgja-twin` in the
rehearsal's time plus about 15 s.
