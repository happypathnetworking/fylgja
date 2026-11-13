# Integrating Fylgja with a system of your own

This page is for someone who runs a source of truth and an orchestration platform of their
own, and wants a change rehearsed on a twin before it reaches the network. Fylgja ships three
pieces, held to three standards ([D-081](../design/decisions.md#d-081)): the **core**, which
turns a blueprint into a twin; a **reader** for each source of truth, which turns that source
into blueprints, Infrahub's and NetBox's; and an **example orchestrator**, which joins the two
to Infrahub or to NetBox through Prefect. You take the first two and run them unchanged. The
third is written to be read once and replaced: it is honest on its main path and on plain
failures, and it is not hardened.

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

Each of its reads is given a **reader document**
([`infrahub-reader-1.schema.json`](../formats/infrahub-reader-1.schema.json)): which
manufacturer and platform pair is which platform package, the artifact that holds a device's
configuration, and whether probes are read. It holds no address and no credential.

The Infrahub reader gives a blueprint or the faults, and never guesses
([D-082](../design/decisions.md#d-082)). It refuses a read, every fault in one pass and no
blueprint, where a list is not read whole, a branch's schema differs from its mapping's table,
or a device in scope has no configuration artifact `Ready` with the bytes its checksum names, or
one generated before the latest write to the intent it renders. It sends no mutation. What it
reads and refuses is [mapping.md](../readers/infrahub/mapping.md) and
[rules.md](../readers/infrahub/rules.md); what its token must read is its README's
[last section](../readers/infrahub/README.md#what-it-sends-and-what-its-token-must-read).

**The reader for NetBox**, `fylgja-netbox`, under
[`readers/netbox/`](../readers/netbox/README.md), installs beside the core's base alone too, and
imports nothing of Prefect, NetBox's client library pynetbox, the Infrahub reader or the core's
server. Its calls are `connect(address, token, *, ca=None)`; `read(conn, *, branch, scope,
document)`, a branch of NetBox's branching plugin, or `main` where `branch` is None, as it
stands, since NetBox reads no earlier time; and `check(conn, *, branch)`
([its README](../readers/netbox/README.md#the-library)). Its reader document
([`netbox-reader-1.schema.json`](../formats/netbox-reader-1.schema.json)) says which manufacturer
and platform pair is which platform package, and which configuration context, if any, declares
the probes. Each device's configuration is what NetBox renders for it at the read, and a read the
changelog or the branch moved under is refused, `read.moved`, to be read again
([D-095](../design/decisions.md#d-095)). What it reads and refuses is
[mapping.md](../readers/netbox/mapping.md) and [rules.md](../readers/netbox/rules.md); what its
token must be allowed is its README's
[last section](../readers/netbox/README.md#what-it-sends-and-what-its-token-must-be-allowed).

## What you replace

The example is three layers ([D-085](../design/decisions.md#d-085)), its change source one for
each source of truth it reads, under [`orchestrator/`](../orchestrator/src/fylgja_orchestrator/):

| Layer | Where | Who replaces it |
|---|---|---|
| The **rehearsal library**: plan, create, step, rehearse, the two documents and the report | `rehearsal/` | Nobody need: it imports the core's client and model alone, and names no source and no workflow engine |
| The **Infrahub change source**: the open proposed change of a branch, its stages, each read through the reader, the report posted | `infrahub/`, with the stage kind [`infrahub/schema/fylgja-stage.yml`](../infrahub/schema/fylgja-stage.yml) | Someone whose source of truth is not Infrahub |
| The **NetBox change source**: a branch by its name, its stages `main`, its marks and its head, a mark taken when its step exists, the request taken off the branch, the report filed as one journal entry | `netbox/`, with the trigger in NetBox that [`netbox/seed/hook.py`](../netbox/seed/hook.py) installs | Someone whose source of truth is not NetBox |
| The **edge**: two Prefect deployments, the command line, and Infrahub's two checks | `edge/`, and [`infrahub/checks/`](../infrahub/checks/) | Someone whose platform is not Prefect, or whose source runs no checks |

The two sources show the seam's two ends ([D-097](../design/decisions.md#d-097)). Infrahub is
read at any earlier time, and its trigger, a check, waits for the rehearsal's answer and
concludes from it. NetBox is read only as it stands, so each step is read when it exists and its
blueprint kept by the core, and its trigger, a webhook sent once, is told nothing: the answer is
the report filed on the branch.

**The edge.** `edge/settings.py` reads once which source to open, `FYLGJA_ORCHESTRATOR_SOURCE`,
`infrahub` where it is unset, or `netbox`, and nine variables of that source: the core at
`FYLGJA_API_ADDRESS` with `FYLGJA_API_TOKEN`; the source at its own address with its own token,
Infrahub at `FYLGJA_INFRAHUB_ADDRESS` with `FYLGJA_INFRAHUB_TOKEN` or NetBox at
`FYLGJA_NETBOX_ADDRESS` with `FYLGJA_NETBOX_TOKEN`; each with an optional `_CA`; and
`FYLGJA_ORCHESTRATOR_SCOPE`, `FYLGJA_ORCHESTRATOR_READER` and `FYLGJA_ORCHESTRATOR_ROOT`. The
other source's three are neither required nor judged. `edge/run.py` wires them to the library
and that source, with no Prefect: that file is the one to copy into another platform.
`edge/flows.py` wraps it in the two flows, `stage-plan` and `twin-rehearse`, each
`(branch: str)`: Infrahub's checks start both, and NetBox's webhook `twin-rehearse` alone.
`edge/serve.py` serves them as `stage-plan/main` and `twin-rehearse/main`, under the same names
whichever source the runner serves, so one Prefect serves one source's runner. A Prefect home
keeps a deployment's id across its runners, as read of a runner restarted, so a run, a check's or
the tag's, goes to whichever runner serves the name; nothing refuses a runner of the other
source serving it, which was not read. Only these two files import Prefect. `edge/cli.py` is
the command `fylgja-orchestrator`, which calls the library in its own process, with no Prefect
and no server:

- `stage list --branch B`: the change's stages, none of them read, and the twins that stand at
  each. It takes no `--scope`, since it reads no stage.
- `stage plan`, `twin create`, `twin step` and `twin rehearse`, each `--branch B`, where
  `--scope S` stands in for `FYLGJA_ORCHESTRATOR_SCOPE`; `twin create` and `twin step` take
  `--twin` and `--stage`, and keep a record of each twin's stage under
  `FYLGJA_ORCHESTRATOR_ROOT`. `twin rehearse` has the source take the request first, as the flow
  does: under NetBox it takes the tag off the branch where the tag is on it.
- `stage mark --branch B --label L`, with `--scope S` as above, the NetBox source's alone: the
  branch read as it stands, its blueprint given to the core and a mark written on the branch.
  Under `infrahub`, where the operator writes the marks, it is refused.
- `serve`, the runner, the one command that loads Prefect.

**The checks**, `fylgja-step` and `fylgja-twin` ([`.infrahub.yml`](../.infrahub.yml)), are glue
on Infrahub's task worker, the standard library and httpx alone (`fylgja_glue.py`). Each finds
the open proposed change of the branch it runs on, starts its deployment, waits, cancels at its
own deadline, reads the run's document and concludes from its `status` alone. They decide
nothing of the rehearsal's and write nothing to Infrahub.

**NetBox's trigger** is NetBox's own: the tag `fylgja-rehearse`, an event rule and a webhook to
Prefect's API, which [`netbox/seed/hook.py`](../netbox/seed/hook.py) installs (`make
netbox-hook`). No code of the example's runs in NetBox, and nothing waits for the run
([The example with NetBox, end to end](#the-example-with-netbox-end-to-end)).

**The change source**, for a source that is neither, is a class that answers the seam below.
Read `infrahub/source.py` or `netbox/source.py` beside `rehearsal/source.py`: each shows one way
to find a change from what a trigger names, order its stages, read each into a blueprint through
a reader, and post a report. Their rules are their own, catalogued in `orchestrator/rules.md`,
[Infrahub's](../orchestrator/rules.md#findings-the-infrahub-change-source) and
[NetBox's](../orchestrator/rules.md#findings-the-netbox-change-source).

## The seams

**API 1, through `fylgja_core.client.Client`.** `Client(address, token, *, ca=None)` puts
blueprints, builds and diffs bundles, applies, verifies and deletes twins, reads runs and reads
the capacity. `follow(record, operations)` follows the run a write of a twin's spec started to
its verdict, from the record the write answered. It takes no timeout: the bound is the caller's,
a platform's time limit or an interrupt. A refusal is a `ProblemError`, with the HTTP status and
the problem document, whose `rule` is stable; a core not reached is a `TransportError`.

**The readers' calls**, over a connection from `connect`: the Infrahub reader's two, `read` and
`head`, and the NetBox reader's one, `read`, of a branch or `main` as it stands
([its README](../readers/netbox/README.md#the-library)). A reader knows no stage, proposed
change or twin: which branch to read, and for Infrahub at what time, is its caller's.

**`ChangeSource`'s four calls**
([`rehearsal/source.py`](../orchestrator/src/fylgja_orchestrator/rehearsal/source.py)), and three
attributes:

- `change(ref) -> Change`: the change a trigger names, with its id, its name, and `where`, the
  change in words for the report;
- `stages(change) -> Sequence[Stage]`: its stages in order, each a label, a description, `where`
  and a pin, which only the source reads;
- `read(stage, scope) -> Read`: the stage read under a scope, its blueprint or none, the
  findings, those that refused it among them, and whether the scope selected no device;
- `post(change, report)`: the report posted, a `Report` of its status, its headline and two
  parts;
- `comment_limit`: the bytes one part of a report may take there, or `None`, as NetBox's is;
- `again`: one sentence that says how the rehearsal is asked for again, which ends the library's
  sentences for a rehearsal not carried through: Infrahub's is `Run the checks again.`, and
  NetBox's ``Set the tag `fylgja-rehearse` on the branch again.``;
- `scope_remedy`: one sentence that says where the scope is checked, which ends the sentence for
  a change with nothing to build: Infrahub's is `Check the scope the checks run with.`, and
  NetBox's `Check the scope the runner is given.`

The library assumes none of these of a source (D-085): that a stage can be read later; that the
source has an object of review; that the trigger is reliable, comes once or waits for the
answer; that the source holds a verdict; that the report is a comment; that configuration is a
stored artifact. So a source whose stages cannot be read twice, or whose trigger is a webhook
sent once, can answer the same four calls: NetBox's is such a source.

**`EdgeSource`'s three more**
([`edge/run.py`](../orchestrator/src/fylgja_orchestrator/edge/run.py)), which only the edge asks:
`is_draft(change)`, whether the change is a draft, which the edge refuses before the core is
asked anything (no NetBox branch is one); `claim(change)`, the request that started the
rehearsal taken, so that it is used once, asked by `run.rehearse` alone and before the library
starts: NetBox's takes the tag off the branch by one `PATCH` of its other tags, and sends
nothing where the tag is not on it, and Infrahub's does nothing, since a proposed change's
checks ask again only when they run again; and `close()`, its connections closed.

**A mark, where a source cannot be read later.** NetBox reads no branch as it stood earlier, so
a step is read when it exists ([D-097](../design/decisions.md#d-097)): `stage mark` reads the
branch as it stands through the reader, gives the blueprint to the core, and only then writes a
journal entry on the branch naming the label, the blueprint's id, the scope and the time read,
so that no mark names a blueprint the core was never given. The rehearsal reads a mark back from
its entry, and its blueprint from the core by its id. So a mark is read through a core that
holds its blueprint, the core it was given to or one given the same intent
([D-100](../design/decisions.md#d-100)), and the example keeps no store: the marks are NetBox's
and the blueprints the core's. A label is unique within its branch and never taken twice, a
change is seeded and marked once for each core it is rehearsed through, and a past step cannot
be marked again, since NetBox reads no earlier time.

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

## The example with Infrahub, end to end

The development host runs the example with Infrahub as CONTRIBUTING's
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

## The example with NetBox, end to end

The development host runs the example with NetBox as CONTRIBUTING's
[With NetBox](../CONTRIBUTING.md#with-netbox) sets it up: the development NetBox, the edge's
Prefect server on port 4200 of the Docker bridge's gateway, the runner of the source `netbox`,
and the core. NetBox's worker reaches Prefect as `host.docker.internal:4200`, the name
[`netbox/dev/compose.override.yml`](../netbox/dev/compose.override.yml) gives the development
host.

```text
operator     --> NetBox       make netbox-change: the branch made from main, a step written
stage mark   --> NetBox       the branch read through the reader, as it stands
stage mark   --> core         the blueprint given (API 1), its id answered
stage mark   --> NetBox       the mark, a journal entry on the branch naming that id
                              (a step written and marked so, each in turn)
operator     --> NetBox       the tag fylgja-rehearse set on the branch
NetBox       --> worker       the event rule matches the branch's update
worker       --> Prefect      POST create_flow_run of twin-rehearse/main, {"branch": <the branch>}
Prefect      --> runner       runs the flow, a process of its own
runner       --> NetBox       the branch by its name, ready; the tag taken off
runner       --> NetBox       the marks' entries; main and the head read through the reader
runner       --> core         each mark's blueprint by its id; plan, look, create, settle, step,
                              verify, destroy (API 1)
runner       --> NetBox       the report, one journal entry, its kind the verdict
runner       --> Prefect      the rehearsal 1 document, filed as the run's artifact
```

1. **The change is built and marked.** `netbox/seed/change.py` (`make netbox-change`) deletes the
   branch `NETBOX_BRANCH` names, `third-link` by default, where it stands, every journal entry on
   it with it, and makes it anew from `main`, waited for until `ready`. It writes the change's two
   steps under the branch's header with the superuser's token, the cable between `n1` and `n3`,
   then the address `192.0.2.1/24` on `n1`'s end, and marks each as soon as it exists by the
   example's own command, `fylgja-orchestrator stage mark --branch <branch> --label <label>`, run
   through `scripts/edge_dev.py run --source netbox` under the example's token. `stage mark`
   (`edge/cli.py`, and `NetBoxSource.mark` in `netbox/source.py`) refuses a label the branch
   already has, `main`, `head` or one that is no label, with nothing read through the reader or
   written; it reads the branch as it stands, gives the blueprint to the core, and then writes
   the mark, a journal entry of kind `info` whose text is the line `Fylgja stage: <label>`, an
   empty line, and `- blueprint: <the id the core gave>`, `- scope: <scope>` and
   `- read: <the read's observed_at>`, a line each (`mark_text`). A read refused writes no mark,
   exits 1 and stops the change, the branch left as it stands for reading. The core must be
   running while the change is marked, since a mark's blueprint is the core's.
2. **The tag.** `netbox/seed/hook.py` (`make netbox-hook`) installs the trigger on `main` with the
   superuser's token, each part found by its name or made, and left: the tag `fylgja-rehearse`,
   limited to branches; the webhook `fylgja-rehearse`, a `POST` to
   `http://host.docker.internal:4200/api/deployments/<id>/create_flow_run`, `<id>` the deployment
   `twin-rehearse/main`'s as Prefect answers it, with the body
   `{"parameters": {"branch": {{ data.name | tojson }}}}`, which writes the branch's name as a
   JSON string, as read of names holding `"` or `\`, and Prefect's basic auth in its
   `additional_headers`; and the event rule `fylgja-rehearse` on a branch's `object_updated` while
   its tags hold `fylgja-rehearse`, its action the webhook. Setting the tag on a branch, in
   NetBox or by `make netbox-change NETBOX_TAG=1`, which sets it last, is the request.
3. **The webhook.** NetBox's worker sends the webhook as a background task, once, whatever is
   answered ([verified-facts.md](../design/verified-facts.md), "NetBox 4.7.5 with
   netbox-branching 1.2.3"). Prefect answers 201 and makes one run of `twin-rehearse/main`, the
   branch's name its one parameter, created about a second after the tag was set in the readings.
   NetBox keeps Prefect's answer as the background task's result, and nothing of it on the branch.
4. **The request taken.** The runner runs the flow (`edge/flows.py`), which reads its settings,
   opens the NetBox source and the core (`edge/run.py`) and hands the branch to `run.rehearse`.
   The source finds the branch named exactly so, and refuses where none is (`NoChange`) or where
   it is not `ready`, merged among them (`Unready`, its status named). Then `claim` takes the tag
   off, before the library starts: one setting of the tag is one rehearsal, and the flow's own
   untagging starts no run, as read. A tag set again while a rehearsal runs, or an edit of the
   branch while it still carries the tag, starts another run, whose `claim` takes the tag off
   where it finds it and sends nothing where it does not, and whose rehearsal deletes the first's
   twin ([D-086](../design/decisions.md#d-086)).
5. **The rehearsal.** Its stages (`stages_of`) are `main` as it stands when the rehearsal reads
   it; each mark, in the order its entry was written; and the **head**, the branch as it stands
   then. A NetBox change has no branch point: its first stage is `main` now, not as it stood when
   the branch was made. `main` and the head are read through the reader, and read again where the
   reader refuses one as moved, `read.moved`, three reads in all and none waited between. A mark
   is read from its entry and its blueprint from the core by its id, held to that id. The library
   then plans, looks, creates, settles, steps, verifies and destroys, as it does for Infrahub.
6. **The journal entry.** The library renders the report, and the source files it (`post`) as one
   journal entry on the branch, the summary, an empty line and the detail, its kind the verdict:
   `success` for `passed`, `danger` for `failed`, and `warning` for `not_rehearsed` and
   `stopped`. NetBox renders a Markdown list only where an empty line stands before it, so the
   source puts one before each list that directly follows a line of text (`spaced`), and changes
   nothing else of the library's text. It sets no bound on the entry's size. The flow files its
   document as the run's artifact, as it does for Infrahub, and nothing reads it back: the report
   gates nothing, and the merge is NetBox's alone.

**A mark the rehearsal cannot use** refuses its stage, by a finding of the source's that names it
([`orchestrator/rules.md`](../orchestrator/rules.md#findings-the-netbox-change-source)): two
entries of one label, `mark.duplicate`; a line of an entry missing, there twice or malformed, or
its label missing, `main`, `head` or not of a label's form, `mark.malformed`; one read under
another scope than the rehearsal's, `mark.scope`; and one whose blueprint the core does not hold,
marked through another core or its store since emptied, `mark.unheld`. The entry alone decides
each but the last, and the core is not asked. Since a label is never taken twice and NetBox
reads no earlier time, the remedies are few. A mark read under another scope is rehearsed under
the mark's scope (`mark.scope`), and one whose blueprint another core holds is rehearsed through
that core (`mark.unheld`). Every other remedy is a deletion in NetBox by someone who may delete
journal entries, which the example's account may not: of two entries of one label, all but one
(`mark.duplicate`); of any other mark the rehearsal cannot use, its entry, and the step is marked
again, which can be done only while the branch still stands at that step; otherwise the change is
seeded again.
`make netbox-change` run again for a branch deletes that branch, its marks with it, and builds
it again.

**`main` moved since the branch was made or last synchronised** is the warning
`stage.main.gained` on the first stage, since the first step then may undo those changes on
the twin. It counts the rows of `main`'s changelog from the branch's `last_sync`, or its `created`
where it was never synchronised, leaving out journal entries, the branch object's own rows, and
the trigger's own webhook and event rule, which no read reads; a tag is counted, since a tag can
be a scope. To rehearse against `main` as it stands, the branch is synchronised and its steps
seeded again.

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

**A trigger that waits for nothing**, as NetBox's webhook is, needs one of the four alone: a
start over HTTP, one request whose body names the change. Prefect's `create_flow_run` takes
NetBox's request as NetBox sends it, `POST /api/deployments/<id>/create_flow_run` with
`Content-Type: application/json`, the basic auth in an `Authorization` header and
`{"parameters": {"branch": <the branch>}}`, and answers 201
([verified-facts.md](../design/verified-facts.md), "Prefect 3.9.2"). The request names the
deployment by its id, which a new Prefect home changes, so `make netbox-hook` is run again after
one: a webhook naming an old id is answered 404 and starts nothing, which NetBox shows only as a
failed background task.

**A lost request stays lost.** NetBox never sends a webhook again: as read, a port that refuses
failed in under a second, and an address that does not answer at NetBox's default timeout of
60 s, and neither was sent a second time. The branch kept its tag and gained no report. NetBox
shows the sending as a failed background task, listed among its queue's failed jobs, and its
words are in the worker's log alone. With one worker, as the development NetBox runs, a setting
made while a sending waits on an address that does not answer waits behind it, up to that
timeout. So Prefect down when the tag is set loses the request: the branch keeps its tag, and
the tag is taken off and set again to ask again. The example sends nothing a second time.

So a branch's tag and journal read two ways ([D-097](../design/decisions.md#d-097)). One that
keeps its tag and gains no report was not rehearsed: its request was lost, or its run started
and was refused before the tag was taken off, by its settings or its reader document, or by the
branch: none of that name, one made anew under the name, one no longer `ready`, or its read or
the tag's removal refused or unanswered by NetBox. Prefect shows such a run as failed, in the
refusal's words. D-097 says such a branch was never started, which is true of a lost request
alone, as [D-100](../design/decisions.md#d-100) restates. One that lost its tag and gained no
report was started: by a flow, whose run in Prefect says what came of it, or by
`twin rehearse` by hand, which takes the tag off too and of which Prefect knows nothing. A tag
set while Prefect answers and no runner serves `twin-rehearse/main` was not read.

## Capacity, for a platform with its own queue

A rehearsal looks before it asks: before anything is created, it asks a dry run of each stage
as the twin it would make, so a stage the runtime has no room for is refused there and nothing is
made ([D-086](../design/decisions.md#d-086)).

A dry run or a run refused for room, `admission.capacity`, ends the rehearsal `not_rehearsed`,
its cause `rehearsal.capacity`, and means "ask again": nothing is wrong with the change. The
library then reads `GET /v1/capacity` to show the room in the report. The example retries
nothing and queues nothing: asking again is running the checks again, or setting the tag again.

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
- **The runner holds the two tokens a rehearsal needs**, the core's and its source's: under
  Infrahub as `FYLGJA_API_TOKEN` and `FYLGJA_INFRAHUB_TOKEN`, the names the edge reads. On the
  development host `make orchestrator-serve` gives them from `local/.env`'s
  `FYLGJA_ORCHESTRATOR_API_TOKEN` and `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, with Prefect's basic
  auth and nothing of the admin's.
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
- **Under NetBox the runner holds two tokens too**, the core's and the NetBox account
  `fylgja-orchestrator`'s, as `FYLGJA_API_TOKEN` and `FYLGJA_NETBOX_TOKEN`. `make
  orchestrator-serve SOURCE=netbox` gives them from `local/.env`'s
  `FYLGJA_ORCHESTRATOR_API_TOKEN` and `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, with Prefect's basic
  auth, and nothing of the superuser's, of the reader's account or of Infrahub's; a command by
  hand is given the same through `scripts/edge_dev.py run --source netbox`, with nothing of
  Prefect's.
- **The NetBox account `fylgja-orchestrator`** is no superuser, and holds four grants
  (`GRANTS` in `netbox/seed/account.py`, made by `make netbox-seed`): `view` of the nine types a
  read lists, and `view` with `render_config` on `dcim.device`, as the reader's account holds
  them, since the source reads through the reader with its own token; `view` and `add` on
  `extras.journalentry`, for its marks and its report; and `view` and `change` on
  `netbox_branching.branch`, for the branch's tags. A grant is by type: `add` on journal entries
  writes an entry on any object, and `change` on branches any member of a branch. It was refused,
  403 each, a change or a delete of a journal entry, its own marks among them, a site's create
  and a branch's sync ([verified-facts.md](../design/verified-facts.md), "NetBox 4.7.5 with
  netbox-branching 1.2.3").
- **NetBox holds Prefect's basic auth.** The webhook carries it in its `additional_headers`,
  written by `make netbox-hook` with the superuser's token from `FYLGJA_ORCHESTRATOR_AUTH`, and it
  opens all of that Prefect's API. The reader's account and the example's are each refused a
  webhook and an event rule, by the list or by the id, 403; but both hold `view` on NetBox's
  changelog, and the webhook's rows in `main`'s changelog hold its `additional_headers`
  unmasked, and its `secret` too, of which the example sets none, so both lesser tokens read the
  auth there, as read on 2026-11-13, and the example's NetBox contract tier holds it. The rows
  outlive the webhook: those of one deleted the day before still held the value it was written
  with, so a value once written stays readable until that changelog's own pruning, or a purge of
  the instance, removes its rows. Replacing the credential removes no row: the old value stays
  readable there, and only stops opening Prefect. As read for those two accounts' grants, which
  have no constraint, an account that may view NetBox's changelog can read a webhook's headers,
  so Prefect's credential is as widely readable as that changelog; a grant with constraints was
  not read. The example accepts this as a known limit: it is a demonstration, whose secrets sit
  together on a development host. Restricting who may view the changelog is by itself no remedy:
  the reader's account and the example's must keep that view, so both still read the header. A
  deployment that shares its NetBox puts a receiver of its own between NetBox and Prefect, so
  that Prefect's credential never enters NetBox ([D-097](../design/decisions.md#d-097),
  [D-100](../design/decisions.md#d-100)), though
  whatever that receiver is sent, a header or a `secret`, the same rows hold; or it gives grants
  that hide the webhook's rows from the accounts that need the changelog, which was not read.
- **No token, password or auth string** is printed, logged, put on a command line, or carried by
  an exception, a document, a check's message, a journal entry or a report.

## What the example leaves out

The example is not hardened ([D-081](../design/decisions.md#d-081)). It leaves out
([D-086](../design/decisions.md#d-086)):

- any reclaim beyond the twin's name: a rehearsal deletes the other twins named for its change at
  its start, and a runner that dies mid-rehearsal leaves its twin until the change is rehearsed
  again or someone deletes it, `fylgja-core twin list` showing it;
- a deadline computed from the packages: a rehearsal has one fixed time limit;
- a retry on a busy runtime: `admission.capacity` ends it `not_rehearsed`;
- a bound on how many rehearsals run at once;
- loss across a step;
- how an engineer marks a step in NetBox: the seed's script runs `stage mark`
  ([D-097](../design/decisions.md#d-097));
- a request sent again: a lost one is asked again by setting the tag again;
- a gate on the merge: NetBox's report gates nothing;
- what a mark's read found beside its blueprint, an omission among it, which is said when the
  mark is taken and is not carried to the rehearsal's report;
- a mark carried from one core to another: a change is seeded and marked once for each core.

Each is the platform's to add, or a later phase's.
