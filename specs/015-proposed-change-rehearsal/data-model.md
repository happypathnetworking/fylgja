# Data model: a proposed change rehearsed on a twin

**Feature**: `015-proposed-change-rehearsal` · **Plan**: [plan.md](plan.md) · **Research**:
[research.md](research.md) (§1 verified, §2 decisions R-01…R-22)

What moves: the twin record to `7`, the findings document's `rehearsal` block
(`rehearsal.schema.json`), the API's `twin.rehearse` and `render: markdown`, the worker's
fifth workflow, `fylgja serve --listen` repeated, two checks in `.infrahub.yml`, the
Compose override, the fixture tool. What does not: bundle `4`, CTM `1`, PSP `0.6`,
contract `0.2`, findings `1`, the API `1`, the three goldens, the fixture's `47b2c449…`,
the twenty activities (FR-031). Each entity names the contract that fixes its wire form.

## 1. The rehearsal

Contract: [contracts/rehearse-command.md](contracts/rehearse-command.md). One run of
`twin.rehearse` over one open proposed change, found by its source branch. Decided by the
server before any run (R-02), run by the workflow `fylgja-rehearse` (R-01), reported by
the server (R-10).

| Part | Where | What |
|---|---|---|
| the stages | `stages.Plan` (014) | every stage of the proposed change resolved, read, compiled and filed, with 014's refusals and warnings; the branch point refused `contract.node.missing` alone passed over (R-03) |
| the baseline stage | the first compiled stage in order | built as a child `fylgja-provision` (already compiled: `BundleID`, `BundlePath`, `ObservedAt`, `Stage`, `Rehearsal`, `StopFollowing: true`), then its wait as `VerifyTwin` on the run's context, `From` the record's `recorded_at`, `BudgetS` the default |
| a rehearsed stage | each compiled stage after the baseline, in order | a child `fylgja-step` with a `StepInput` the server built (R-05), whose wait is the step's own (`observe`) |
| the deadline | `rehearsal.Deadline` (R-09) | the stages' budgets summed from the node plans and the mechanism constants, under `rehearsal.Ceiling` (3,600 s); a workflow timer that cancels the children's context |
| the destroy | a child `fylgja-destroy` on a disconnected context | always, last, but after a baseline whose provision could not start because another run holds its id: that run touched nothing (T078) |
| the reclaim | the server, before the start (R-04) | a twin whose record's `rehearsal` names a run that is not running is destroyed first, through the destroy run |

**States of the run**, as the result's `outcome` says it and the document's status maps
it (R-08):

```
 rejected (before any run; exit 1)           : a stage refused (014's rules), the deadline unfit, a run in flight, the host held;
                                               or the run's baseline provision refused at its start, its id held: nothing touched, no destroy
 ok (0)                                      : every rehearsed stage passed; warnings and the baseline's findings notwithstanding
 nonconforming (5)                           : a stage failed (diverged, or a finding the baseline lacked); the twin destroyed
 error (2)                                   : a stage's step could not run, was rejected by its locks or cancelled, its wait incomplete; the baseline's
                                               provision ended error, rejected or cancelled (T081); the deadline; the interrupt; after the destroy
 failed (3)                                  : the baseline's provision ended failed and cleaned up
 unclean (4)                                 : the destroy left something, whatever the stages did
```

## 2. A stage of the rehearsal

One entry per stage of the plan, in order (`rehearsal.schema.json` `$defs/stage`):

| Field | From | Meaning |
|---|---|---|
| `ref`, `label`, `description`, `at_source`; `branch`, `at` once resolved | the plan's stage | 014's shapes |
| `bundle_id` | the plan | `null` when refused |
| `role` | R-03, the run | `refused` (the passed-over branch point), `baseline`, `rehearsed`, `not_reached` |
| `verdict` | `rehearsal.Verdict` (R-07) | `refused`, `baseline`, `passed`, `failed`, `error`, `not_reached` |
| `findings` | the plan's, the child's and the wait's | this stage's findings, each also in the document's list; verify's as warnings with the stage prefixed |
| `provision` | the baseline's child result | `{outcome, run, cleanup?}`; `null` on every other stage |
| `step` | the step child's result | `{outcome, phase?, restarted, recreated, created, pushed[{node, outcome, rule?}], timings, run}`; `null` on the baseline |
| `wait` | the baseline's `VerifyTwin`, or the step's `observe` | `{outcome, budget_s, reads, after_s}`; `null` when it did not run |
| `verify` | `wire.VerifyResult.Counts` (R-07) | `{host_name, port_enabled, neighbor, record}` counts of the wait's last read; `null` when none |
| `new_findings` | R-07 | the wait's failing assertions, by rule and object, that the baseline's wait did not have; `[]` otherwise |
| `took_s` | the run's clock | the stage's whole time: its child plus its wait |

**The verdict**, a pure function of the baseline's failing set and the stage's child
result and wait:

```
baseline       : the first compiled stage; its wait's failing set is the baseline findings
passed         : step outcome stepped or unchanged, and the wait's failing (rule, object) ⊆ the baseline's
failed         : step outcome diverged (any phase); or the wait's failing holds a (rule, object) not in the baseline's
error          : step outcome rejected, error or cancelled before its stage; wait incomplete; the deadline or an interrupt cut it
not reached    : every stage after the first that is not passed
refused        : the branch point passed over by R-03
```

`verify.record.holds` is never among a wait's failing entries (the record's claims are
not waited on), and a wait that `settled` has none.

## 3. The baseline findings

The baseline stage's wait, `VerifyTwin` with `RunID` the rehearsal's (so the record is
not written, `Recorded: false`), gives `wire.StepWait`: its `Failing` entries
(`{rule, object, message}`) are the **baseline findings**, reported as the baseline's
(`rehearsal.baseline.findings`), carried as warnings in the document, and failing nothing.
A later stage's wait is compared against them by `(rule, object)`. Not M11's *baseline*
(a node's deploy configuration): the glossary keeps both.

## 4. The deadline

`rehearsal.Deadline(stages []DeadlineStage) (deadlineS int)`, from each compiled stage's
`[]wire.NodePlan` (the host check's plan, read in the server as a dry run reads it), the
largest of each budget over the stage's nodes (Constitution II):

```
baseline  = CheckHost 30 + StopFollowing 30 + Stage 60 + deploy + (readiness + 15) + (push + 15) + Record 30 + (wait 120 + 30)
step      = InspectTwin 30 + CheckHost 30 + CheckHost 30 (the plan) + Stage 60 + deploy + (readiness + 15) + (push + 15) + Record 30 + (wait 120 + 30)
destroy   = PlanTeardown 30 + destroy + Unstage 30
deadline  = baseline + Σ steps + destroy ; refused when > Ceiling (3600)
```

The fixture (SR Linux: deploy 180, readiness 60, push 30, destroy 60): 600 + 630 + 630 +
120 = 1,980 s for the branch point refused, two marks and the head; the baseline's
stop-following bound (`FollowBudget`, 30 s), which its provision runs before it builds, was
added at T082, the figure 1,950 s before it. The check's
`timeout` is the ceiling, the destroy's whole budget (120 s), 300 s for the work before
`start` and a margin of 180 s: 4,200 s.

## 5. The twin record: `twin.json` `7`

Contract: [contracts/rehearse-command.md](contracts/rehearse-command.md) §"twin.json 7";
the `6` schema frozen under `internal/lab/testdata/contracts/014-proposed-change-stages/`.

| Key | `6` | `7` |
|---|---|---|
| `twin_version` | `"6"` | `"7"` |
| `rehearsal` | — | `{"workflow_id": "fylgja-rehearse", "run_id": …}` or `null`, required; written by the create's record from `RecordInput.Rehearsal`, kept by a step's record |

`wire.RehearsalRef{WorkflowID, RunID}`; `ProvisionInput.Rehearsal *RehearsalRef` (nil in
every input and recorded history of a run not started by a rehearsal, omitted when nil);
`RecordInput.Rehearsal`; `TwinRecord.Rehearsal` (no omitempty: `7` writes an explicit
`null`, as `stage` does). A `6` record reads with `Rehearsal` nil. `twin show`'s
`record.rehearsal` and `twin verify`'s `twin.rehearsal` carry it (`show.schema.json`,
`verify.schema.json`).

## 6. The workflow's input and result (`internal/provision`, wire-crossing data)

```
RehearseInput    {ProposedChange {ID, Name, Branch, Draft}, ResolvedAt, DeadlineS, CeilingS,
                  Stages []RehearseStage, Version}
RehearseStage    {Ref, Label, Description, AtSource, Branch, At, BundleID, BundlePath,
                  Refused *{Rule, Message}, Role, Diff (the pair, stages.schema.json $defs/step),
                  Provision *ProvisionInput (the baseline), Step *StepInput (a rehearsed stage), WaitS}
RehearseResult   {Outcome (ok | stage_failed | stage_error | baseline_failed | cut | cancelled | rejected),
                  Stages []RehearsedStage, Reached (the stage the run stopped at), DeadlineHit,
                  StartedAt, EndedAt, UsedS, Destroy *DestroyResult, Findings}
RehearsedStage   {Ref, Verdict, Run *RunRef, Provision *ProvisionResult, Step *StepResult,
                  Wait *wire.StepWait, Counts *wire.VerifyCounts, NewFindings []wire.StepFinding, TookS}
```

The workflow branches on `Role`, the children's outcomes and the verdict, never on a
stage's content; every path ends in the destroy child but `rejected`'s, whose baseline
provision could not start because another run holds its id, so nothing was touched. `StepResult` gains `WaitCounts
*wire.VerifyCounts`, `wire.VerifyResult` gains `Counts *VerifyCounts`, both omitted when
nil, so every recorded history replays. No new activity.

## 7. The report

Contracts: [contracts/rehearsal.schema.json](contracts/rehearsal.schema.json),
[contracts/rehearse-command.md](contracts/rehearse-command.md).

- **The document**: `findings_version` `1`, operation `twin.rehearse`, the `rehearsal`
  block (`$defs/rehearsal`: the proposed change, `resolved_at`, `deadline_s`,
  `ceiling_s`, `used_s`, `reclaimed`, `run`, `baseline`, `stages`, `destroy`,
  `reproduce`), the findings, `subject.branch` and `subject.run_id`.
- **The text**: the progress lines as every run prints them, a `stage <ref>:` heading
  before each child, one line per stage with its verdict after the run, the closing line;
  the findings as text.
- **The markdown** (`render: "markdown"`, `document.markdown`, `twin rehearse
  --markdown`): the heading (Fylgja, the proposed change, the run, `resolved_at`, the
  status), the table (one row per stage), the Mermaid drawing (one node per stage, one
  edge per step labelled with what it changed), the stages as `stage list` prints them,
  the warnings, the baseline findings, the reproduce commands on a failure, the fidelity
  caveat. Rendered by `rehearsal.Markdown` from the block alone; never a configuration
  line, a device diff, a token or a login.
- **The reproduce commands** (`reproduce`): `fylgja twin create --stage <baseline>`, one
  `fylgja twin step --stage <ref> --allow-restart` per rehearsed stage up to the failed one,
  `fylgja twin verify`, `fylgja twin destroy`; `[]` when no stage failed.

## 8. The API and the client

| Operation | Path | `args` | Files | Takes an interrupt |
|---|---|---|---|---|
| `twin.rehearse` | `/v1/twin/rehearse` | `branch` | none | from `start` |

`render`: `"text"`, `"json"`, `"markdown"`. Under `markdown` the `out` and `err` frames are
`text`'s, and the `document` frame carries `markdown` beside `text` on an operation that
has one (`twin.rehearse` alone). `start.workflow_id` gains `fylgja-rehearse`. The client:
`fylgja twin rehearse --branch <b> [--markdown] [--json]`; `--markdown` prints the markdown
alone on stdout; `--markdown` with `--json` is cobra's refusal, exit 2, nothing sent.

## 9. The checks (Infrahub's runtime, glue)

Contract: [contracts/checks.md](contracts/checks.md).

| Check | Class, file | `timeout` | Asks | Writes | Concludes |
|---|---|---|---|---|---|
| `fylgja-step` | `FylgjaStep`, `infrahub/checks/fylgja_step.py` | 300 | `stage.plan` `{branch}` | nothing | success unless a stage is refused as intent (a branch point's `contract.node.missing` excepted), the stages unlistable, or Fylgja unreachable, refusing the token or the version; the plan's text as the message |
| `fylgja-twin` | `FylgjaTwin`, `infrahub/checks/fylgja_twin.py` | 4200 | `twin.rehearse` `{branch}`, render `markdown`, with a stream | one `CoreChangeThread` (`change` the proposed change, `label` `Conversation`) holding one `CoreThreadComment` (`text` the markdown) per run | on a draft: success, nothing asked; else `ok` → success, any other status → failure; the report's text as the message |

Shared: `infrahub/checks/fylgja_api.py` (the two variables, the request, the frames, the
proposed change by `branch_name`, the comment). Each check's query is `fylgja_branch`
(`infrahub/queries/branch.gql`, `{ Branch { name } }`), the cheap read the SDK requires.
The check's environment: `FYLGJA_API_ADDRESS` (`host.docker.internal:7650` from the
override) and `FYLGJA_API_TOKEN` (from `local/.env` through Compose), nothing else of
Fylgja's. Its message never carries the token; a fault names the address it tried, which
is no credential, as US2's acceptance scenario 4 has it.

**The comment**: a `CoreChangeThread` on the proposed change, labelled `Conversation` and
unresolved as the view labels its own, holding one `CoreThreadComment` whose `text` is the
markdown, which the proposed change's overview shows; a `CoreChangeComment`, which it does
not show, is never written (research §5.9). The comment carries no author or stamp field
of its own in 1.11.2; its first line is the report's heading, which names the run and
`resolved_at`, so comments of one proposed change read in order. A proposed change's
delete takes its threads and their comments with it.

## 10. The server, the override and the host

Contract: [contracts/server-and-host.md](contracts/server-and-host.md).

| Variable | Who | Value |
|---|---|---|
| `--listen` (repeatable) | `fylgja serve` | `127.0.0.1:7650` and `<docker0>:7650` on the lab host; one `http.Server` over every listener |
| `FYLGJA_API_ADDRESS` | the task workers (override) | `host.docker.internal:7650`, a name Docker resolves to the bridge through `extra_hosts: host.docker.internal:host-gateway` |
| `FYLGJA_API_TOKEN` | the task workers (override, `${FYLGJA_API_TOKEN}` from `local/.env`) | the one token |

The bring-up script's `fylgja` part starts the server on both addresses, reading the
bridge from `docker network inspect bridge`, and its `infrahub` part re-runs `compose up
-d` when the override was (re)installed. The reclaim and the refusals of the host are §1's.

## 11. The fixture tool and test support

Contract: [contracts/fixture-tool.md](contracts/fixture-tool.md). New: `-ready`,
`-run-checks <artifact|user>`, `-add-interface <device>:<name>`; `MarkReady`,
`RunUserChecks`, `AwaitUserChecks` (the run already begun, as a creation's, awaited without
asking for one; convergence, T065), `UserChecksOf`, `CommentsOf`, `AddInterface`,
`ServeRepository`, `DeleteRepository`. The deletion order is unchanged: stages, then proposed changes (their
comments and validators go with them), then the branch.
