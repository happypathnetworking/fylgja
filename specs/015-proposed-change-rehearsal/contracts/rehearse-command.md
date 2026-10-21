# Contract: `twin rehearse`, the operation `twin.rehearse`, the report, `twin.json` 7

Extends [contracts/cli.md](../../../contracts/cli.md) and [contracts/api.md](../../../contracts/api.md)
as 014 leaves them; at the close each gains a section "015: the rehearsal" that says what
this file says. **Everything not named here is as 014 left it.** Identifiers, exit statuses
and the JSON documents are the contract; text is illustrative except where quoted.

## The command

```
fylgja twin rehearse --branch <b> [--markdown] [--json]
```

A client's command: one request, `POST /v1/twin/rehearse`, the frames printed, the exit by
the document. It needs a server, Infrahub, the bundle store, the workflow service, a worker,
Docker and containerlab on the server's and the worker's `PATH`, and both images where the
stages need them: everything `twin create`, `twin step`, `twin verify` and `twin destroy`
need. Every refusal with an identifier is the server's. `--branch` is required (`--branch
is required`, exit 2, no request); an empty `--branch=` is `stage.ref.invalid` at `start`.
`--markdown` prints the markdown rendering alone on stdout, nothing else there, and exits by
the document; `--json` prints the document alone; both together are cobra's own refusal,
exit 2, with no request. No `--allow-restart`, `--wait` or `--dry-run`: a rehearsal's twin
is its own, each wait is the step's default budget, and `stage plan` is its dry run.

### What the server does, in order

Each step's refusal ends the request with its document and nothing started:

1. **The plan**: the open proposed change whose source branch is `b` is found and every
   stage resolved, read, compiled and filed in the store, as `stage plan` does, with 014's
   refusals and warnings (`stage.kind.absent`, `stage.unknown`, `stage.artifact.stale`,
   `stage.label.reserved`, …; `stage.main.moved` as a warning). A stage refused refuses the
   rehearsal with the plan's findings: status `rejected`, exit 1 (`error`, 2, for
   `operation.failed` and `intent.at.precision`), the host untouched. **The one exception**:
   a branch point whose one rejection is `contract.node.missing` at `read` is kept as a row
   (`role`, `verdict` `refused`) and passed over.
2. **The baseline**: the first compiled stage in order. When it is the only one, the
   warning `rehearsal.steps.none` is filed and the rehearsal goes on.
3. **The deadline**: the stages' budgets summed from the node plans (data-model.md §4);
   over the ceiling it is `rehearsal.deadline.unfit`, exit 1, at `start`, naming the time
   the stages need and the ceiling.
4. **The runs in flight**: `fylgja-rehearse`, `fylgja-provision`, `fylgja-step` or
   `fylgja-destroy` running is `run.in_flight`, exit 1, naming the run.
5. **The host**: a twin whose record's `rehearsal` names a `fylgja-rehearse` run that is not
   running is **reclaimed**: the destroy run is started and followed as `twin destroy`
   does, its events in the answer after the notice `reclaiming the twin of rehearsal run
   <id>`, the warning `rehearsal.twin.reclaimed` filed, the report's `reclaimed` block set;
   a destroy that leaves something refuses the rehearsal with `cleanup.incomplete`, exit 4.
   The reclaim never cancels a run: its start reads the runs in flight again, and a
   rehearsal, provisioning or step run begun since step 4 refuses the rehearsal,
   `run.in_flight` naming it, exit 1, with nothing cancelled or destroyed and no `reclaimed`
   block. A destroy run in flight is attached to.
   Then the host check of the baseline bundle, in this process as a dry run makes it: a
   lab or a twin directory (`host.lab.present`, `host.twin.present`, naming what holds the
   host and that `twin destroy` clears it), the memory sum, an unset login, an absent image,
   a package not loaded, each under its identifier at `host_check`, exit 1.
6. **The start**: `start` frame with `fylgja-rehearse`, the run started
   (`WorkflowExecutionErrorWhenAlreadyStarted`; `run.in_flight` by the fixed id; no worker
   `run.worker.absent`), the `run` frame, then the follow.
7. **The follow and the report**: every event of the run and of its children, each child
   announced by the notice `run <workflow> <id>` and preceded by a `stage <ref>: …` line;
   after the run closes, the stages read again for `rehearsal.stage.moved` and
   `rehearsal.change.closed`; then the document.

### The run, `fylgja-rehearse`

Children under their fixed ids, each refused beside any other run: `fylgja-provision` for
the baseline (already compiled, as a rebuild's child is; `StopFollowing: true`; its record
carrying the rehearsal), then `VerifyTwin` (the baseline's wait, the default budget, from the
record's time, written into no record), then `fylgja-step` per later stage in order
(`--allow-restart`'s behaviour; the default wait; the run reads containerlab's plan itself),
then `fylgja-destroy` on a disconnected context, always, but when the baseline's
`fylgja-provision` could not start because another run holds its id: that run touched
nothing, starts no destroy, which would tear down the other run's lab, and is `rejected`,
exit 1, `run.in_flight` naming `fylgja-provision` (FR-007). The run stops at the first stage
whose verdict is not `passed`. The deadline is a timer on the run's clock: when it passes, the
children's context is cancelled (a provision cleans up; a step records diverged, D-036), and
the destroy follows. The operator's first interrupt cancels the run the same way and waits
for its destroy; the second stops waiting (`run.cancelled`, the run goes on to its destroy).
An answer that stops waiting so, or whose result cannot be read, keeps the run it started:
the block names it, with every stage `not_reached` and `destroy` `null`, since the answer
learned nothing of them, and the closing line says `rehearsal error: run fylgja-rehearse
<id> was started and its end was not read (<why>); it goes on to its destroy, and fylgja twin
show says where it is`, with no stage line (T079).
A client that goes away leaves the run running to its destroy.

### Status and exit

| Status | Exit | When |
|---|---|---|
| `ok` | 0 | every rehearsed stage passed; the baseline's findings and the warnings notwithstanding |
| `rejected` | 1 | refused before any run: a stage refused, the deadline unfit, a run in flight, the host held; or the run's baseline provision refused at its start, another run holding its id, the run touching nothing and starting no destroy |
| `error` | 2 | a stage's step could not run, was rejected by its locks or cancelled before its stage; the baseline's provision ended `error`, `rejected` or `cancelled`, building nothing to clean up (T081); its wait incomplete; the deadline cut the rehearsal; the operator's interrupt; `operation.failed`; after the destroy |
| `failed` | 3 | the baseline could not be built: its provision ended `failed` and cleaned up |
| `unclean` | 4 | the destroy left something; `cleanup.incomplete` says what and that `twin destroy` clears it |
| `nonconforming` | 5 | a stage failed: diverged, or a finding the baseline did not have; the twin destroyed |

No status, step, operation or exit is new beyond the operation.

### The text

```
rehearsal of proposed change "third link" (18df…) on branch change-1, draft: 4 stages; deadline 33m0s (ceiling 1h0m0s)
change-1/branch-point: refused (contract.node.missing)
  rejection contract.node.missing [step read] main: branch defines FylgjaContract but holds no instance of it
change-1/seeded: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"; baseline
change-1/third-link: branch change-1 at 2026-10-16T17:30:00.000000+00:00 (given), "third link"
change-1/head: branch change-1 at 2026-10-16T17:30:11.884302+00:00 (head)
run fylgja-rehearse 01a1…
stage change-1/seeded: creating the twin
run fylgja-provision 02b2…
step host check: begins
…
step record: done in 0.1s
stage change-1/seeded: verify: settled after 3.2s (2 reads)
stage change-1/third-link: stepping
run fylgja-step 03c3…
…
step observe: settled after 6.1s (4 reads)
stage change-1/head: stepping
…
destroying the twin
run fylgja-destroy 04d4…
…
removed lab fylgja (3 containers)
removed twin directory /srv/fylgja/local/twin
stage change-1/branch-point: refused (contract.node.missing)
stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline
stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed
stage change-1/head: unchanged in 0.9s; settled after 1.0s (1 read); 19 held, 0 failed, 0 skipped; passed
rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1980s deadline
```

Each child's lines come under a `stage <ref>:` line, the destroy's under `destroying the
twin`. The baseline's progress line names its verify's wait, `stage <ref>: verify: settled
after …`, without its counts. Once the run has closed come what the destroy removed, then
one line per stage, the baseline's counts on its own, and the closing line (T025, T029,
T041). A step that restarted or recreated a node names each with the seconds its readiness
took (`stepped in 95.3s (restarted n3 61.2s; push n1 2.5s, n3 2.6s)`), and a node the step
was cut before awaiting alone (T070). A step the deadline or an interrupt cut keeps its phase
and names what it touched, as a diverged one does (`cancelled at phase push: restarted n3
61.2s; landed n3; not landed n1 (not attempted)`, `cancelled at phase readiness: restarted
n3`), and the table's cell alike (`cancelled at push; restarted n3 61.2s; push n3; not landed
n1`; T094). A failed stage's line names why (`diverged at phase
push: restarted n3 61.2s; landed n3; not landed n1 (push.refused)`, or `failed:
verify.neighbor n1:ethernet-1/3`), and the lines after it read `not reached`; the closing
line says `rehearsal nonconforming: stage change-1/bad-port failed at phase push; the twin
is destroyed; reproduce it by hand:` followed by the commands, one per line, indented:
`fylgja twin create --stage` the baseline, `fylgja twin step --stage <ref> --allow-restart`
for each rehearsed stage up to the failed one, `fylgja twin verify` and `fylgja twin
destroy`. A rehearsed stage at the branch and `at` of the last stage a command named, the
baseline's or a step's, has no step of its own, since `twin step` would refuse it
`step.target.current` and the twin is already there; run in order, the commands make the
rehearsal's steps and its verify (FR-015), and a failed stage so left out is reproduced by
the verify after the steps before it (T099). A
refusal prints the plan's lines and the findings. The reclaim prints `reclaiming the twin of
rehearsal run <id>` and the destroy's lines before the run. A run whose baseline provision
could not start because another run holds its id prints `rehearsal rejected: the run touched
nothing, since a run already holds the id of its baseline's provision; no destroy was needed`
(T078). The findings, with the
baseline's as warnings prefixed by the stage, print as every document prints them, on
stderr.

### The markdown

Rendered from the document and the plan's steps between the stages (`rehearsal.Markdown`),
GitHub-flavoured:

```markdown
## Fylgja rehearsed proposed change "third link" on change-1

Run `fylgja-rehearse 01a1…`, stages resolved at 2026-10-17T14:02:11Z. Status **ok**. 118.4s of the 1980s deadline (ceiling 3600s).

| stage | at | bundle | step | wait | verify | new findings | verdict |
|---|---|---|---|---|---|---|---|
| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | | | | | refused (contract.node.missing) |
| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c6c1d96… | created | settled after 3.2s | 15 held, 0 failed, 0 skipped | — | baseline |
| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d05dc990… | stepped 4.5s; push n1, n3 | settled after 6.1s | 19 held, 0 failed, 0 skipped | none | passed |
| change-1/head | 2026-10-16T17:30:11.884302+00:00 | cc1ca493… | unchanged | settled after 1.0s | 19 held, 0 failed, 0 skipped | none | passed |

```mermaid
flowchart LR
  s0["change-1/branch-point<br/>refused"]
  s1["change-1/seeded<br/>baseline"]
  s2["change-1/third-link<br/>passed"]
  s3["change-1/head<br/>passed"]
  s0 -. "not computed" .-> s1
  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2
  s2 -- "unchanged" --> s3
```

**Stages** (Infrahub's view does not show them):

- `change-1/branch-point` main at 2026-10-16T17:20:19.944651+00:00 (branch point)
- `change-1/seeded` change-1 at 2026-10-16T17:25:30.118244+00:00 (written) "after the link is cabled"
- …

**Warnings**: stage.main.moved … (none when there are none)

**Baseline findings** (reported, failing nothing): none

**Reproduce by hand** (on a failure alone):

```
fylgja twin create --stage change-1/seeded
fylgja twin step --stage change-1/bad-port --allow-restart
fylgja twin verify
fylgja twin destroy
```

*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing.*
```

**A run that did not reach a stage.** One whose baseline provision could not start, another
run holding its id, is headed `## Fylgja did not rehearse proposed change …`, its run line
saying that it touched nothing and needed no destroy (T078). One whose end was not read is
headed `## Fylgja started rehearsing proposed change …`, its run line saying that it was
started, why its end was not read, and that it goes on to its destroy, which `fylgja twin
show` follows; its stages read `not read` in the table and the drawing, and nothing says that
no run was started (T079).

**The warnings** list each warning a stage filed once, however many of its steps filed it,
naming the stages that did (``- `artifact.interface.unrepresented` n1:ethernet-1/99: …
(stages bad-port, head)``), as `stage plan` prints one under each stage (T075). The run's
own are listed as they came: the rehearsal's, and `stage.main.moved`, which the plan files
on the branch point but which is the branch's.

A Mermaid label is quoted; `"` in a name is written `#quot;`, `<` and `>` as `#lt;` and
`#gt;`; a line break is `<br/>`. An edge's label is the step's text with no content: nodes
and links added or removed, nodes changed with their reasons, artifacts changed by node;
a step not computed is a dotted edge. Under 1.11.2 a comment renders through react-markdown
with `remark-gfm` (tables), `remark-breaks` and `rehype-mermaid` (research §1.2).

**Its length** (`rehearsal.CommentMax`, found at T055, research §5.7): Infrahub 1.11.2
refuses a text attribute when 3 and its UTF-8 length reach 4096 bytes, so the markdown is
never longer than 4,092. A report that would be names each finding by its identifier and
object alone, identical ones once with their count (``- `push.refused` n1 (×2)``), since the
check's message holds the text; gives the table brief, each step by its outcome alone
(`diverged at push`) and its new findings by the first two and how many more (`… and 198
more`); and cuts a proposed change's name, or a branch's, in the heading to 120 bytes with
an ellipsis. Should that still be too long, whole sections are left out by an order of
preference, the baseline's findings first, then the drawing, the warnings, the stages, the
findings and the reproduce commands: they are kept from the last of it back while each still
fits, so one earlier in it is kept when it fits once a later one was left out, as a long
drawing is left out while the baseline's findings are kept (T105). **The table is never
left out, and keeps every stage's reference and verdict**:
should the brief table not fit beside the heading, the run line and the caveat, it gives
each stage's reference and verdict alone (`| stage | verdict |`), and should even that not
fit, as no ceiling bounds a refusal's stages, as many stages as fit in order and a last row
`| … and <n> more | |` (T083). The heading, the run line, the table and the caveat are
always kept, and a line before the caveat says what was shortened: `*To fit what Infrahub
keeps of a comment (4092 bytes), each finding is named by its identifier and object alone,
and the table each step by its outcome and its new findings by the first few[; … are left
out]; fylgja-twin's message is the whole report as text.*`, the table's clause reading `;
the table gives each stage's reference and verdict alone[, and the last <n> are left out
of it]` when it was shrunk further. A report that fits is rendered whole, as above.

## The API

| Operation | Path | `args` | Files in | Files out | Takes an interrupt |
|---|---|---|---|---|---|
| `twin.rehearse` | `/v1/twin/rehearse` | `branch` | | | from `start` |

- `branch` present and empty is `--branch=`, refused `stage.ref.invalid` at `start`;
  absent is `--branch is required`, `operation.failed`, exit 2; both before the server
  connects to Infrahub.
- **`render` gains `"markdown"`**: the `out` and `err` frames are as under `"text"`, and
  the `document` frame carries `markdown` beside `text` on an operation that has a
  markdown rendering, `twin.rehearse` alone; every other operation answers `markdown` as it
  answers `text`, with no `markdown` field. [api.schema.json](../../../contracts/api.schema.json)'s
  `render` enum and `$defs/frame`'s `document` frame move; `start.workflow_id`'s enum gains
  `fylgja-rehearse`.
- A refusal before the start is the `document` frame alone, with no `start`. A reclaim's
  destroy is followed inside the answer before the `start` frame, with no `run` frame of
  its own, as `twin.destroy`'s is.
- The interrupt is `POST /v1/streams/{stream}/interrupt`, as for a create.
- `api.Version` stays `1`: a new operation, a new render value and a new frame field,
  which a client of M13 ignores.

### `twin show`, `twin verify`, `twin destroy`, `stage list` beside a rehearsal

- `twin show`'s kind line for a rehearsal's twin: `pinned at …, stage change-1/seeded, of
  rehearsal run fylgja-rehearse 01a1…; not following`; its `show.record.rehearsal` carries
  `{workflow_id, run_id}`, absent when the record names no rehearsal. While the run is in
  flight: `in flight: run fylgja-rehearse 01a1… at step step (run fylgja-step 03c3… at step
  push), stepping towards stage change-1/third-link`, and the kind line ends `; rehearsal run fylgja-rehearse 01a1…
  is at stage change-1/third-link, step push`.
- `twin verify`'s first line names the rehearsal's run after the stage; its `verify.twin`
  carries `rehearsal`, `null` when the record names none.
- `twin destroy` during a rehearsal prints `cancelling rehearsal run 01a1…; waiting for its
  destroy`, follows it, then its own destroy, which finds nothing; a create or a step beside
  a rehearsal is `run.in_flight` naming it. A step asks the workflow service first, before
  it reads the host or Infrahub, so it is never refused as an orphan during the baseline's
  provision or as diverged after a failed stage; its dry run asks nothing, as `twin create
  --dry-run` does not (T080).
- `stage list` marks a rehearsal's twin as it marks any twin. While the run is in flight,
  and while a dead rehearsal's twin waits for its reclaim, the record names a stage of the
  proposed change, whose row carries `← twin`, or `← twin (diverged towards …)` after a
  failed step (its `stages.rows[].twin` true under `--json`); nothing there names the
  rehearsal, which `twin show` does. Once the rehearsal ends its twin is gone, and no row
  is marked.

## `twin.json` 7

`contracts/twin.schema.json`, `$id https://fylgja.dev/contracts/twin/v7`, `twin_version`
`"7"`: `rehearsal` is required, `{"workflow_id": "fylgja-rehearse", "run_id": "…"}` or
`null`; everything else of `6` stands. A create's record writes it from its input, a step's
record keeps it. The `6` schema is frozen under
`internal/lab/testdata/contracts/014-proposed-change-stages/`, and a `6` record reads with no
rehearsal.

## Identifiers

| Rule | Severity, exit, step | When |
|---|---|---|
| `rehearsal.deadline.unfit` | rejection, 1, `start` | the stages' summed budgets exceed the ceiling; names the time needed and the ceiling |
| `rehearsal.twin.reclaimed` | warning, 0, `destroy` | a twin of a rehearsal whose run was no longer running was destroyed before the start; names the run and what was removed |
| `rehearsal.steps.none` | warning, 0, `resolve` | one stage alone compiled: it was built, verified and destroyed, and no step was rehearsed |
| `rehearsal.stage.failed` | rejection, 5 (`nonconforming`), the phase's step for a divergence, `observe` for a finding | the stage failed; names the phase and the nodes landed and not landed, or the finding by rule and object |
| `rehearsal.stage.error` | rejection, 2, the step reached | the stage's step could not run, was rejected by its locks or cancelled before its stage, or its wait could not complete; or the baseline's provision ended `error`, `rejected` or `cancelled`, at the step it stopped at |
| `rehearsal.baseline.failed` | rejection, 3, `provision` | the baseline could not be built: its provision ended `failed`; the provision child's own findings stand beside it |
| `rehearsal.deadline.cut` | rejection, 2, the step reached | the deadline passed: names the stage in progress, each finished stage's time and the deadline |
| `rehearsal.stage.moved` | warning, 0, `resolve` | after the run, a rehearsed stage no longer resolves to the `(branch, at)` it was rehearsed at, or is gone; the head included |
| `rehearsal.change.closed` | warning, 0, `resolve` | after the run, the proposed change is no longer open |

`run.cancelled` (an interrupt; at the step reached), `run.in_flight`, `run.worker.absent`,
`run.service.unreachable`, `host.*`, `cleanup.incomplete`, every `stage.*`, `step.*` and
`verify.*` keep their identifiers. The baseline's and each rehearsed stage's verify
findings are in the document as **warnings**, their object prefixed by the stage
(`change-1/seeded: n1:ethernet-1/2`), since a rejection would end the document `rejected`
and the baseline's fail nothing; a new finding fails its stage through
`rehearsal.stage.failed`, which names it.

## Workflows and activities

One workflow is added, `fylgja-rehearse` (Constitution VIII, D-051); no activity, budget
or version marker is added or changed, and the nine recorded histories replay. `StepResult`
gains `wait_counts` and `wire.VerifyResult` `counts`, both omitted when absent.

## Formats and versions

| Format | Version | Change |
|---|---|---|
| the API | `1` | `twin.rehearse`; `render: markdown`; `document.markdown`; `start.workflow_id` `fylgja-rehearse` |
| findings | `1` | operation `twin.rehearse`; the `rehearsal` block by `$id` in `rehearsal.schema.json`; `show.record.rehearsal`, `verify.twin.rehearsal` |
| `twin.json` | `7` | `rehearsal` |
| bundle manifest, PSP, CTM, contract | `4`, `0.6`, `1`, `0.2` | none |
