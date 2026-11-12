# Integrating Fylgja with a system of your own

This page is for someone who runs a source of truth and an orchestration platform of their
own, and wants a change rehearsed on a twin before it reaches the network. Fylgja ships three
pieces, held to three standards ([D-081](../design/decisions.md#d-081)): the **core**, which
turns a blueprint into a twin; a **reader**, which turns one source of truth into blueprints,
the first Infrahub's; and an **example orchestrator**, which joins the two to Infrahub through
Prefect. You take the first two and run them unchanged. The third is written to be read once and
replaced: it is honest on its main path and on plain failures, and it is not hardened.

The page walks through the example and says, at each part, which files to read and what you
would write in their place. The terms are in the [glossary](glossary.md).

## What you take unchanged

**The core and its API.** `fylgja-core` installed alone is the model package and the client
library: PyYAML, jsonschema, httpx and referencing, as ranges, and nothing of the server
([D-084](../design/decisions.md#d-084)). The server, `fylgja-core-server`, is the extra
`fylgja-core[server]`, pinned exactly, and runs as CONTRIBUTING's
[Running the core](../CONTRIBUTING.md#running-the-core) says. Every client reaches it through
API 1 alone ([`api-1.openapi.yaml`](../formats/api-1.openapi.yaml),
[D-025](../design/decisions.md#d-025)): it knows no source, branch or stage, and takes the
blueprint as its one input ([blueprint 1](../formats/blueprint-1.schema.json)). Read
`core/src/fylgja_core/client.py` for the client.

**The reader for Infrahub**, `fylgja-infrahub`, under
[`readers/infrahub/`](../readers/infrahub/README.md). It installs beside the core's base alone,
and imports nothing of Prefect, Infrahub's SDK or the core's server. Its calls:

- `connect(address, token, *, ca=None)`, the connection every other call reads through. It reads
  Infrahub's version first, and warns on one its contract tier has not passed on.
- `read(conn, *, branch, at, scope, document, generated_since=None)`, a branch at a time under a
  scope, `tag:<name>`: a `Result` of the blueprint, its findings, and whether the scope selected
  no device. `at` is sent to Infrahub as given; `generated_since` is a time at which a
  regeneration of the configurations is known to have completed.
- `head(conn, *, branch, scope)`, the first instant after the branch's latest write, the time a
  read of the branch as it stands is pinned at; `Refused`, with its findings, where it cannot
  answer one.

Each read is given a **reader document**
([`infrahub-reader-1.schema.json`](../formats/infrahub-reader-1.schema.json)): which
manufacturer and platform pair is which platform package, the artifact that holds a device's
configuration, and whether probes are read. It holds no address and no credential.

The reader gives a blueprint or the faults, and never guesses
([D-082](../design/decisions.md#d-082)). It refuses a read, every fault in one pass and no
blueprint, where a list is not read whole, a branch's schema differs from its mapping's table,
or a device in scope has no configuration artifact `Ready` with the bytes its checksum names, or
one generated before the latest write to the intent it renders. It sends no mutation. What it
reads and refuses is [mapping.md](../readers/infrahub/mapping.md) and
[rules.md](../readers/infrahub/rules.md); what its token must read is its README's
[last section](../readers/infrahub/README.md#what-it-sends-and-what-its-token-must-read).

## What you replace

The example is three layers ([D-085](../design/decisions.md#d-085)), under
[`orchestrator/`](../orchestrator/src/fylgja_orchestrator/):

| Layer | Where | Who replaces it |
|---|---|---|
| The **rehearsal library**: plan, create, step, rehearse, the two documents and the report | `rehearsal/` | Nobody need: it imports the core's client and model alone, and names no source and no workflow engine |
| The **Infrahub change source**: the open proposed change of a branch, its stages, each read through the reader, the report posted | `infrahub/`, with the stage kind [`infrahub/schema/fylgja-stage.yml`](../infrahub/schema/fylgja-stage.yml) | Someone whose source of truth is not Infrahub |
| The **edge**: two Prefect deployments, the command line, and Infrahub's two checks | `edge/`, and [`infrahub/checks/`](../infrahub/checks/) | Someone whose platform is not Prefect, or whose source runs no checks |

**The edge.** `edge/settings.py` reads nine variables once: the core at `FYLGJA_API_ADDRESS`
with `FYLGJA_API_TOKEN`, Infrahub at `FYLGJA_INFRAHUB_ADDRESS` with `FYLGJA_INFRAHUB_TOKEN`, each
with an optional `_CA`, and `FYLGJA_ORCHESTRATOR_SCOPE`, `FYLGJA_ORCHESTRATOR_READER` and
`FYLGJA_ORCHESTRATOR_ROOT`. `edge/run.py` wires them to the library and the source, with no
Prefect: that file is the one to copy into another platform. `edge/flows.py` wraps it in the two
flows a check starts, `stage-plan` and `twin-rehearse`, each `(branch: str)`, and
`edge/serve.py` serves them as `stage-plan/main` and `twin-rehearse/main`; only these two files
import Prefect. `edge/cli.py` is the command `fylgja-orchestrator`, which calls the library in
its own process, with no Prefect and no server:

- `stage list --branch B`: the change's stages, none of them read, and the twins that stand at
  each. It takes no `--scope`, since it reads no stage.
- `stage plan`, `twin create`, `twin step` and `twin rehearse`, each `--branch B`, where
  `--scope S` stands in for `FYLGJA_ORCHESTRATOR_SCOPE`; `twin create` and `twin step` take
  `--twin` and `--stage`, and keep a record of each twin's stage under
  `FYLGJA_ORCHESTRATOR_ROOT`.
- `serve`, the runner, the one command that loads Prefect.

**The checks**, `fylgja-step` and `fylgja-twin` ([`.infrahub.yml`](../.infrahub.yml)), are glue
on Infrahub's task worker, the standard library and httpx alone (`fylgja_glue.py`). Each finds
the open proposed change of the branch it runs on, starts its deployment, waits, cancels at its
own deadline, reads the run's document and concludes from its `status` alone. They decide
nothing of the rehearsal's and write nothing to Infrahub.

**The change source**, for a source that is not Infrahub, is a class that answers the seam below.
Read `infrahub/source.py` beside `rehearsal/source.py`: it shows one way to find a change from
what a trigger names, order its stages, read each into a blueprint through a reader, and post a
report. Its rules are its own, catalogued in
[`orchestrator/rules.md`](../orchestrator/rules.md#findings-the-infrahub-change-source).

## The seams

**API 1, through `fylgja_core.client.Client`.** `Client(address, token, *, ca=None)` puts
blueprints, builds and diffs bundles, applies, verifies and deletes twins, reads runs and reads
the capacity. `follow(record, operations)` follows the run a write of a twin's spec started to
its verdict, from the record the write answered. It takes no timeout: the bound is the caller's,
a platform's time limit or an interrupt. A refusal is a `ProblemError`, with the HTTP status and
the problem document, whose `rule` is stable; a core not reached is a `TransportError`.

**The reader's two calls**, `read` and `head`, over a connection from `connect`. The reader
knows no stage, proposed change or twin: which branch and time to read is its caller's.

**`ChangeSource`'s four calls**
([`rehearsal/source.py`](../orchestrator/src/fylgja_orchestrator/rehearsal/source.py)), and one
attribute:

- `change(ref) -> Change`: the change a trigger names, with its id, its name, and `where`, the
  change in words for the report;
- `stages(change) -> Sequence[Stage]`: its stages in order, each a label, a description, `where`
  and a pin, which only the source reads;
- `read(stage, scope) -> Read`: the stage read under a scope, its blueprint or none, the
  findings, those that refused it among them, and whether the scope selected no device;
- `post(change, report)`: the report posted, a `Report` of its status, its headline and two
  parts;
- `comment_limit`: the bytes one part of a report may take there, or `None`.

The library assumes none of these of a source (D-085): that a stage can be read later; that the
source has an object of review; that the trigger is reliable, comes once or waits for the
answer; that the source holds a verdict; that the report is a comment; that configuration is a
stored artifact. So a source whose stages cannot be read twice, or whose trigger is a webhook
sent once, can answer the same four calls.

**The two documents**, the plan ([`plan-1.schema.json`](../formats/plan-1.schema.json)) and the
rehearsal ([`rehearsal-1.schema.json`](../formats/rehearsal-1.schema.json)). What runs the
library reads two members of each, and nothing else need be read:

- `status`: a plan is `planned`, `refused`, `empty` or `unfinished`, and only `planned` passes; a
  rehearsal is `passed`, `failed`, `not_rehearsed` or `stopped`, and only `passed` passes. A
  value you do not know is a failure, never a success.
- `headline`: the verdict and its cause, two lines of plain text, for a check's message or a
  notification.

Every other member is the report's or a command's
([Constitution XII](../design/constitution.md#xii-every-field-earns-its-place)).

## The example, end to end

The development host runs the example as CONTRIBUTING's
[Running the example orchestrator](../CONTRIBUTING.md#running-the-example-orchestrator) sets it
up: the development Infrahub, the edge's Prefect server on port 4200 of the Docker bridge's
gateway, the runner, and the core.

```text
operator     --> Infrahub     marks the stages on main, then opens the proposed change
Infrahub     --> task worker  runs fylgja-twin and fylgja-step, at the branch's commit
task worker  --> Prefect      starts twin-rehearse/main with {"branch": <the source branch>}
Prefect      --> runner       runs the flow, a process of its own
runner       --> Infrahub     the proposed change, its marks and its validation; each stage
                              read through the reader
runner       --> core         plan, look, create, settle, step, verify, destroy (API 1)
runner       --> Infrahub     the report, one thread of two comments
runner       --> Prefect      the rehearsal 1 document, filed as the run's artifact
task worker  <-- Prefect      the run's state, polled, then its document
task worker  --> Infrahub     success or failure, the headline its message
```

1. **The proposed change is opened.** The stages are marked first: each mark is a `FylgjaStage`,
   written on `main`, naming its branch as text, with a label and an optional `as_of`, so it is
   written before any proposed change exists ([D-088](../design/decisions.md#d-088)). Infrahub
   runs a proposed change's checks when it is created, a draft or not, and when its checks are
   run again; leaving draft starts nothing. The development seed writes two marks and, with
   `PROPOSED_CHANGE=1`, the proposed change (`make infrahub-seed`).
2. **Infrahub's check.** A proposed change runs the checks as its source branch was made with
   them: a branch keeps the registration's commit it was made with, so a branch made before an
   import runs the check files of before it. Infrahub runs `fylgja-step` and `fylgja-twin` on a
   task worker. Each reads the open proposed change of its branch through the check's own client
   of Infrahub. `fylgja-twin` passes a draft having started nothing; `fylgja-step` plans a draft
   too.
3. **The deployment.** The check reads `FYLGJA_ORCHESTRATOR_ADDRESS` and
   `FYLGJA_ORCHESTRATOR_AUTH`, finds the deployment by its name and starts a run of it with the
   branch as its one parameter.
4. **The rehearsal.** The runner runs the flow, which reads its settings, opens the source and
   the core, and hands the branch to `run.rehearse`. The source finds the open proposed change
   whose source branch it is, and the edge refuses a draft. Its stages are the **branch point**,
   `main` read at the time Infrahub gives the branch's cut; the **marks**, by their time; and the
   **head**, the branch read once the proposed change's artifact validation has completed, waited
   for up to 240 s, its completion given to the reader as `generated_since`; where no validator
   appears within 120 s, as for a branch that changes no device, the head is read on its
   artifacts' stamps alone. The library then plans every stage, looks with a dry run of each,
   creates the baseline, settles it, steps and verifies each later stage, stops at the first
   that fails, and destroys the twin on every path ([D-086](../design/decisions.md#d-086)).
5. **The thread.** The library renders the report from the document
   ([D-087](../design/decisions.md#d-087)), and the source posts it as one thread, labelled
   `Fylgja rehearsal`, of two comments, the summary and the detail, each within 4,092 bytes.
   Infrahub removes a proposed change's threads with it.
6. **The check's conclusion.** The flow files its document as the run's one artifact, of type
   `fylgja-document`, keyed `fylgja-twin-rehearse-<run id>`. The check polls the run's state
   every 5 s, reads the document by the run's id once the run has ended, and passes exactly when
   its `status` is `passed`; its message is the `headline`, and says the report is in the
   proposed change's thread.

Two facts of Infrahub 1.11.11 bear on any deployment of these checks
([verified-facts.md](../design/verified-facts.md), "Infrahub 1.11.11"):

- **A task worker with no clone of the registration's commit fails its checks.** A recreated
  worker holds no clone, and a check of a read-only registration run there fails
  `NodeNotFoundError`, the registration asked for as a `CoreRepository`. An import with no new
  commit clones on the one worker that runs it. So `make infrahub-register` reads each running
  task worker for the commit's tree and asks an import, and again every 30 s, until each holds
  it, and refuses after 300 s, naming each worker that lacks it and ending "run make
  infrahub-register again". Every worker of a deployment must hold the commit before a proposed
  change is opened.
- **The two checks have run on a task worker, and each started its run from there, in phase 8's
  two acceptance runs** on 2026-11-12: a proposed change the maintainer created in Infrahub's UI,
  rehearsed once with the core on the local driver and once with the core on the cluster, both
  checks concluding `success`, on one worker each time
  ([verified-facts.md](../design/verified-facts.md), "Infrahub 1.11.11", "A proposed change
  created by the maintainer in the UI, rehearsed through its own check, on the local driver" and
  "A proposed change created by the maintainer in the UI, rehearsed through its own check, on the
  cluster's core"). No test here runs them on a task worker: the contract tier runs their glue in
  its own process, against a Prefect server on loopback, as a check runs it.

## What your platform must give

A check, or whatever stands in for one, needs four things of the platform: to **start** a run
over HTTP with a parameter, to **wait** on it for many minutes, to **cancel** it, and to be
**handed a document** back by the run's id. Prefect 3.9.2 gives each to a caller with httpx
alone ([verified-facts.md](../design/verified-facts.md), "Prefect 3.9.2"), and the glue asks for
them so:

| Need | Prefect 3.9.2 |
|---|---|
| Start | `GET /api/deployments/name/<flow>/main`, then `POST /api/deployments/<id>/create_flow_run` with `{"parameters": {"branch": …}}` |
| Wait | `GET /api/flow_runs/<id>`, every 5 s, until its state is `COMPLETED`, `FAILED`, `CANCELLED` or `CRASHED` |
| Cancel | `POST /api/flow_runs/<id>/set_state` with a state of type `CANCELLING`, no `force` |
| Document | `POST /api/artifacts/filter` by the run's id and the type `fylgja-document`, its `data` a JSON string |

Creates sent together were answered 503 but one, and each was accepted when asked again, so a
503 to the deployment's read, to the start or to the document's read is asked once more, 5 s
on, and a second is a failure; a poll of the run's state is not asked again so, since the next
poll asks. Every request is bounded, 5 s to connect and 30 s to answer.

**The deadlines** are nested so that the innermost fires first. The rehearsal's own time limit
is 3,600 s, and the flow's 3,900 s, which leaves 300 s for the library's end after its limit:
its cancel, its deletion and its post. A check keeps a deadline of its own before Infrahub's
`timeout`, which ends it with no message of its own: `fylgja-twin`'s `timeout` is 4,260 s and its
deadline 240 s less, 4,020 s; `fylgja-step`'s 900 s and 660 s, over its flow's 600 s.

**After a cancel**, Prefect gives the flow's body a `BaseException` and about 30 s of clean-up
before it kills the flow's process; after a flow's time limit, a clean-up of 20 s was read to run
whole, and a longer one was not read. The example spends it on one request, as the code
reads: the library's own handler asks the core to delete the twin, which API 1 answers at once
and which also cancels the run in flight, waits for nothing, and raises again. The flow's
`finally` then files a document only where it was handed one, which on that path it never is,
and adds no request and no wait. A run whose clean-up did nothing read `CANCELLED` 3.2 s after
`CANCELLING`; in the contract tier's cancel during a held apply, the core listed no twin of the
change 2.00 s after `CANCELLED`, the runner's log not showing the delete itself.

**A run that ends with no document is concluded from its state**, and never as passed: a run
`CANCELLED` is a rehearsal stopped, its twin's deletion asked; a run `FAILED` and named
`TimedOut` passed its time limit; any other end is named with its state's message. Where the run
has not ended when the check must close, the check fails saying so.

## Capacity, for a platform with its own queue

A rehearsal looks before it asks: before anything is created, it asks a dry run of each stage
as the twin it would make, so a stage the runtime has no room for is refused there and nothing is
made ([D-086](../design/decisions.md#d-086)).

A dry run or a run refused for room, `admission.capacity`, ends the rehearsal `not_rehearsed`,
its cause `rehearsal.capacity`, and means "ask again": nothing is wrong with the change. The
library then reads `GET /v1/capacity` to show the room in the report. The example retries
nothing and queues nothing: asking again is running the checks again.

A platform with a queue of its own is where the retry belongs. It re-runs a change whose
document reads `not_rehearsed` with `rehearsal.capacity` as its cause, and may read
`GET /v1/capacity`, `Client.capacity()`, to decide when ([D-076](../design/decisions.md#d-076)).
The reading is a look and never a reservation: it is taken outside the core's admission lock,
and admission decides, with the same reading taken under its lock, so a change asked again may
be refused again.

## Credentials

- **One token a principal.** The core's token file holds a hash and a principal a line, and
  never a token. The example's runner has a principal of its own, `orchestrator`, and its own
  token of the core's, never a person's.
- **The runner holds the two tokens a rehearsal needs**, as `FYLGJA_API_TOKEN` and
  `FYLGJA_INFRAHUB_TOKEN`, the names the edge reads. On the development host `make
  orchestrator-serve` gives them from `local/.env`'s `FYLGJA_ORCHESTRATOR_API_TOKEN` and
  `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, with Prefect's basic auth and nothing of the admin's.
- **The checks hold no token of the core's or of Infrahub's.** A task worker is given the
  platform's address and its basic auth alone, `FYLGJA_ORCHESTRATOR_ADDRESS`, a host and a port
  with no scheme, and `FYLGJA_ORCHESTRATOR_AUTH`
  ([`infrahub/dev/compose.override.yml`](../infrahub/dev/compose.override.yml)). The rehearsal's
  code and its tokens stay in the runner.
- **The Infrahub account `fylgja-orchestrator`** has one role, in one group, of four
  permissions (`infrahub/seed/account.py`): `object:Core:ChangeThread:create:allow_default` and
  `object:Core:ThreadComment:create:allow_default`, which a thread and its comments take;
  `global:edit_default_branch:allow_default`, since both are written on `main`; and the
  instance's own `object:*:*:view:allow_all`. The three alone read nothing, every kind refused
  403, and a view of every kind with the default decision does not read the proposed change's
  branch. D-085 names three; the fourth was read to be needed
  ([D-093](../design/decisions.md#d-093)).
- **Rotating the account's token.** `make orchestrator-env` makes a token and appends or
  replaces the line only where the line is missing, or its token is refused by Infrahub or
  answered as another account's; a live token of the account is kept. So a token that leaked is
  deleted in Infrahub first. On 1.11.11 the token list answers the caller's own tokens, and takes
  a JWT login: asked with the admin's API token it was refused, and a delete of the account's
  token with the admin's JWT was answered 404. So, as the admin, give
  the account a new generated password (`CoreAccountUpdate`); log in as the account (`POST
  /api/auth/login`); with its JWT, list its tokens (`InfrahubAccountToken`) and delete each
  (`InfrahubAccountTokenDelete`); then run `make orchestrator-env`, which reads the line refused
  and replaces it with a new token made by the account's own login. Nothing of either token is
  printed.
- **No token, password or auth string** is printed, logged, put on a command line, or carried by
  an exception, a document, a check's message or a report.

## What the example leaves out

The example is not hardened ([D-081](../design/decisions.md#d-081)). It leaves out
([D-086](../design/decisions.md#d-086)):

- any reclaim beyond the twin's name: a rehearsal deletes the other twins named for its change at
  its start, and a runner that dies mid-rehearsal leaves its twin until the change is rehearsed
  again or someone deletes it, `fylgja-core twin list` showing it;
- a deadline computed from the packages: a rehearsal has one fixed time limit;
- a retry on a busy runtime: `admission.capacity` ends it `not_rehearsed`;
- a bound on how many rehearsals run at once;
- loss across a step.

Each is the platform's to add, or a later phase's.
