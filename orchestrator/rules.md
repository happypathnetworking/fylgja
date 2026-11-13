# Rules of the example orchestrator

Every finding the example orchestrator files has a stable dotted rule id, as the core's do
(Constitution X), and its documents, its checks and its tests match on the id, never on the
wording. These rules are the example's own, never the core's
([`formats/README.md`](../formats/README.md), note 11); the core's are in
[`docs/rules.md`](../docs/rules.md). Each is filed as a finding of a plan 1 or a rehearsal 1
document ([`plan-1.schema.json`](../formats/plan-1.schema.json),
[`rehearsal-1.schema.json`](../formats/rehearsal-1.schema.json)), or, for the commands' own,
beside a command's answer, its sentence the finding's message, and the code names each by a
constant of [`rules.py`](src/fylgja_orchestrator/rehearsal/rules.py).

In a sentence, `{k}` is the stage's number among the change's stages and `{label}` its label.
`{first}` is the first failure quoted: `<object>: <message> (<rule>)`, the message's final full
stop dropped and the message cut to 300 characters, the last of them `…`, the object and its
colon left out where the failure names none. A sentence with no stage in progress drops its
`at stage {k}, {label}` or `of stage {k}, {label}` clause. `{twin}` is the twin's name. Three
are the change source's own words, which the library takes from it and never says itself
([D-097](../design/decisions.md#d-097)): `{Again}` is the source's `again`, the sentence that
says how the rehearsal is asked for again, whole; `{again}` is that sentence as the end of
another, its first letter lowered and its final full stop dropped; and `{scope_remedy}` is the
source's `scope_remedy`, the sentence that says where the scope is checked, whole. The Infrahub
source's are `Run the checks again.` and `Check the scope the checks run with.`, and the NetBox
source's ``Set the tag `fylgja-rehearse` on the branch again.`` and `Check the scope the runner is
given.` A row names its other placeholders.

## The rehearsal's errors

A rehearsal's status is given by its document's first error finding, the cause, and by
nothing else ([D-086](../design/decisions.md#d-086)): `passed` where there is none; `failed`
where the change failed at a stage; `not_rehearsed` where the rehearsal could not be carried
through for a reason that is not the change's; `stopped` where it was stopped before anything
could be said of the change. The report's first sentence is the cause's sentence
([D-087](../design/decisions.md#d-087)). A rehearsal ended by an exception it does not
conclude from, an interrupt or a cancel of whoever runs it among them, writes no document, and
its caller concludes `stopped` ([D-085](../design/decisions.md#d-085)). The first two rules
are the plan's own, filed in its document; a rehearsal that ends at its plan files the same
finding as its cause.

| Rule | Severity | Status | Sentence |
|---|---|---|---|
| `rehearsal.stages.none` | error | `not_rehearsed` | No stage of the change selects a device in scope {scope}, so there is nothing to build. {scope_remedy} ({scope} is the scope the stages are read under.) |
| `stage.refused` | error | `failed` | Stage {k}, {label}, could not be built: {first}. Nothing was rehearsed. |
| `rehearsal.baseline.failed` | error | `failed` | The baseline, stage {k}, {label}, could not be created: {first}. Nothing is said about the stages after it. |
| `rehearsal.stage.failed` | error | `failed` | *By a dry run:* The runtime cannot build stage {k}, {label}: {first}. *By a step `failed`, or `rejected` for anything but the runtime's room, an image or its set-up:* The core refused the step to stage {k}, {label}: {first}. *By one `diverged` with an error beside `step.diverged`:* The step to stage {k}, {label}, failed and left the twin diverged: {first}. *By verify:* Verify found {m} failure(s) at stage {k}, {label}, that the baseline did not have, the first {first}. ({m} failure(s) is `1 failure`, `2 failures`.) |
| `rehearsal.capacity` | error | `not_rehearsed` | The runtime has no room for the twin of stage {k}, {label}: {message} Nothing is wrong with the change: {again} when the runtime has room. ({message} is the core's, whole.) |
| `rehearsal.image.absent` | error | `not_rehearsed` | An image the twin needs is not on the runtime: {message} Import it there, then {again}. ({message} is the core's, whole.) |
| `rehearsal.admission.refused` | error | `not_rehearsed` | The runtime refused the twin of stage {k}, {label}: {first}. That is the runtime's set-up, not the change: correct it, then {again}. |
| `rehearsal.core.unreachable` | error | `not_rehearsed` | *No answer (the client's `TransportError`):* The core did not answer: {error}. Check that it runs and that FYLGJA_API_ADDRESS names it, then {again}. *An answer of another API version, or a run that cannot be followed to its verdict (`UnsupportedVersion`, `FollowError`):* The core answered, but not as this library expects: {error}. Check the core's version against this library's, then {again}. ({error} is the client's text, a final full stop dropped.) |
| `rehearsal.core.refused` | error | `not_rehearsed` | *On 401 or 403:* The core refused the token ({rule}). Put a token whose hash the core's token file holds in FYLGJA_API_TOKEN, then {again}. *Else:* The core refused a request the rehearsal needs: {status} {rule}: {detail} Read the core's log, then {again}. ({status} is the answer's HTTP status, {rule} and {detail} its problem's.) |
| `rehearsal.source.failed` | error | `not_rehearsed` | The change's stages could not be read from its source ({type}). Check that the source answers, then {again}. ({type} is the exception's type, and nothing of its text.) |
| `rehearsal.twin.held` | error | `not_rehearsed` | An earlier rehearsal's twin, {twin}, was not removed within 120 s, so this rehearsal did not start. Remove it with fylgja-core twin destroy {twin}, then {again}. |
| `rehearsal.limit.passed` | error | `stopped` | The rehearsal passed its time limit of {limit_s:g} s at stage {k}, {label}, and was stopped. Nothing is said about the change: {again}, or raise the limit. ({limit_s:g} is the rehearsal's time limit in seconds, as its caller's `Limits` gives it: the edge's is 3600.) |
| `rehearsal.run.cancelled` | error | `stopped` | *A create's, or a step's before its apply began:* The {operation} run of the twin was cancelled by another client, so the rehearsal stopped at stage {k}, {label}. {Again} *A step's after its apply began (`diverged`, `step.diverged` its only error):* The step run of the twin was cancelled by another client after its apply began, which left the twin diverged, so the rehearsal stopped at stage {k}, {label}. {Again} ({operation} is the run's operation, create or step.) |
| `rehearsal.twin.deleted` | error | `stopped` | The twin {twin} was deleted while the rehearsal ran, by a newer rehearsal of this change or by hand, so it stopped at stage {k}, {label}. The newer rehearsal's report stands. |

## The rehearsal's warnings

A warning is filed after the cause, and changes no status.

| Rule | Severity | Status | Sentence |
|---|---|---|---|
| `rehearsal.steps.none` | warning | none | Only stage {k}, {label}, builds, so the twin was created and verified there and no step was rehearsed. |
| `rehearsal.twin.reclaimed` | warning | none | The twin {twin}, left by an earlier rehearsal of this change, was removed before this one started. |
| `rehearsal.report.unposted` | warning | none | The report could not be posted on {where} ({type}); the status stands. ({where} is the change in words, {type} the exception's type.) |
| `rehearsal.twin.left` | warning | none | *Its deletion waited for:* The twin {twin} was not removed within 120 s: read it with fylgja-core twin show {twin}, and remove it with fylgja-core twin destroy {twin}. *Asked alone:* The twin {twin}'s deletion was asked and not waited for: fylgja-core twin show {twin} says whether it is gone. *Not asked:* The twin {twin} may still be there: remove it with fylgja-core twin destroy {twin} once the core answers. |

## The commands' own

`twin create` and `twin step` take one twin to a stage of a change, and file these beside what
they answer, never in a document: no rehearsal files them, so none is a rehearsal's cause. A
command keeps a record of the stage each twin it took stands at, trusted only while its
blueprint id is the one the twin runs ([D-086](../design/decisions.md#d-086)). The two errors
are a command's refusal of its target, which starts no run, and are `failed`, as every error
has a status. Each names the twin as its object; `{twin}` is the twin, `{where}` the change in
words, `{label}` a stage's label and `{scope}` the scope the stages are read under.

| Rule | Severity | Status | Sentence |
|---|---|---|---|
| `step.target.required` | error | `failed` | Nothing says which stage of {where} twin {twin} stands at, so it cannot be stepped to the next: name the stage to step it to. (A step with no stage named, where the twin has no record of the change or one not trusted.) |
| `step.target.unknown` | error | `failed` | *A stage named that the change has not:* {where} has no stage {label}. *A create with none named, where every stage is empty in scope:* No stage of {where} selects a device in scope {scope}, so there is none to create the twin at. *A step with none named, the record's stage gone from the change:* Twin {twin} stands at stage {label}, which {where} no longer has: name the stage to step it to. *A step with none named, the record's stage the last:* Twin {twin} stands at stage {label}, the last of {where}: there is no stage after it. |
| `step.target.current` | info | none | Twin {twin}'s spec is stage {label}'s already, so no run was started. (Where the twin runs that stage's blueprint, its record is written at that stage, so a step with no stage named goes on past it; where the last run of that spec did not end `ok`, the record stays where it was.) |
| `record.twin.stale` | info | none | The record of twin {twin} says it stands at stage {label} of {where}, but the twin runs another blueprint now, so the record is not trusted. (Beside `step.target.required`.) |

## Findings: the Infrahub change source

The example's Infrahub change source, [`fylgja_orchestrator.infrahub`](src/fylgja_orchestrator/infrahub/source.py),
files these in a stage's read, beside the reader's own
([`readers/infrahub/rules.md`](../readers/infrahub/rules.md)), and names each by a `RULE_*`
constant of its own: the rehearsal library names no source's rules
([D-085](../design/decisions.md#d-085)). An error refuses the stage, which the library files
as `stage.refused`, so it is `failed`; a warning or an info changes no status. `{label}` is the mark's
label, `{branch}` the proposed change's source branch, `{destination}` the branch it goes into,
`{cut}` the time `{branch}` was cut, as Infrahub answered it, and `{change}` the proposed
change's id.

| Rule | Severity | Status | Sentence |
|---|---|---|---|
| `stage.label.reserved` | error | `failed` | The mark {label} on branch {branch} is labelled as a stage the source makes of every change, branch-point or head, so it is not read: label it otherwise. (Its object is the mark's label.) |
| `stage.at.unresolved` | error | `failed` | *A mark with no time:* The mark {label} on branch {branch} has no as_of, and Infrahub gave no time of its writing, so there is no time to read the branch at: give the mark an as_of. *A time that does not parse:* The mark {label} on branch {branch} stands at {at}, which does not parse as an ISO 8601 time with a zone, so there is no time to read the branch at: give the mark an as_of that does. (Its object is the mark's label; {at} is its time, quoted; such a mark is ordered after every mark with a time.) |
| `stage.main.moved` | warning | none | {destination} has moved since {branch} was cut at {cut}: the branch point reads {destination} as it was then. (The branch point is decided by {destination} read at {cut}; where that gives a blueprint, {destination}'s head is asked as a comparison alone, and this is filed where {destination} read at its head gives another blueprint, or where its head is refused with `scope.empty`, the devices in scope gone since {cut}; a head refused otherwise, or a read there that gives no blueprint, files nothing. Its object is {destination}.) |
| `stage.validation.unfinished` | warning | none | The artifact validation of proposed change {change} had not completed 240 s after it was first asked for, so the head of {branch} is read on its artifacts' stamps alone, with no generated_since. (Its object is {branch}.) |
| `stage.validation.absent` | info | none | No artifact validation of proposed change {change} appeared 120 s after it was first asked for, so the head of {branch} is read on its artifacts' stamps alone, with no generated_since. (Its object is {branch}. A proposed change whose branch changes no device has no artifact validator, so this is expected there; one was also read to appear 70.5 s after its create where its checks queued behind another proposed change's, design/verified-facts.md, "Infrahub 1.11.11".) |

## Findings: the NetBox change source

The example's NetBox change source, [`fylgja_orchestrator.netbox`](src/fylgja_orchestrator/netbox/source.py),
files these in a stage's read, beside the reader's own
([`readers/netbox/rules.md`](../readers/netbox/rules.md)), and names each by a `RULE_*`
constant of its own: the rehearsal library names no source's rules
([D-085](../design/decisions.md#d-085), [D-097](../design/decisions.md#d-097)). An error
refuses the stage, which the library files as `stage.refused`, so it is `failed`; a warning
changes no status. `{label}` is the mark's label, `{branch}` the branch's name, `{entry}` the id
of the mark's journal entry, `{scope}` the scope the rehearsal reads under, and `{time}` the
branch's `last_sync`, or its `created` where that is null. A mark's errors are filed from its
entry alone, the core unasked, but `mark.unheld`, which the core's answer decides. A label is
unique within its branch and is never taken twice, and NetBox reads no branch as it stood
earlier ([D-097](../design/decisions.md#d-097)), so a step is marked again only once its entry is
deleted and only while the branch still stands at that step: `{Redo}` is the sentence `Have someone
who may delete journal entries delete entry {entry} in NetBox and mark the step again, which can be
done only while the branch still stands at that step; otherwise seed the change again.`, and
`{redo}` the same with its first letter lowered.

| Rule | Severity | Status | Sentence |
|---|---|---|---|
| `mark.duplicate` | error | `failed` | Branch {branch} has {n} marks labelled {label}, journal entries {entries}: a label is unique within its branch. Delete all but one. (Its object is the label; `{entries}` are the ids of its entries in the order written. The stage stands at the first's place.) |
| `mark.malformed` | error | `failed` | The mark {label} on branch {branch}, journal entry {entry}, is not read: {fault}. {Redo} (Its object is the stage's label: the mark's label, but `journal entry {entry}` for a mark with no label, whose sentence begins `The mark on branch`, or one labelled `main` or `head`, so that no mark stands as a second stage of either. `{fault}` is the first of: it has no label; the label is `main` or `head`, or is no label, 1 to 40 lowercase letters, digits and hyphens beginning and ending with a letter or a digit; a line of `- blueprint:`, `- scope:` and `- read:` is missing or there more than once; the blueprint's id is not 64 lowercase hexadecimal characters; the scope or the time read is empty.) |
| `mark.scope` | error | `failed` | The mark {label} on branch {branch}, journal entry {entry}, was read under scope {marked}, and this rehearsal reads under {scope}. Rehearse under {marked}, or {redo} (Its object is the label; `{marked}` is the scope its entry names, and `{redo}` here marks the step again under {scope}.) |
| `mark.unheld` | error | `failed` | The core holds no blueprint {id}, which the mark {label} on branch {branch} names: a mark belongs to the core it was given to. Rehearse through that core, or seed and mark the change again for this one. *The core answering a document that is not the blueprint of that id:* The core answered another document than the blueprint {id}, which the mark {label} on branch {branch} names: a mark belongs to the core it was given to. Rehearse through that core, or seed and mark the change again for this one. (Its object is the label; `{id}` is the first 12 characters of the blueprint's id. The first is filed where the core answers 404 `blueprint.not_found`, the second where the id the core's own rule gives the document it answered is not the mark's; any other refusal of the core's is raised.) |
| `stage.main.gained` | warning | none | main has gained {n} changes since branch {branch} was made or last synchronised, at {time}, counted of every kind but a journal entry's, a branch's own, a webhook's and an event rule's, and the marks were taken against main as it stood then: the first stage is main as it stands, so the first step may undo those changes on the twin. To rehearse against main as it stands, synchronise the branch and seed its steps again. (`{n} changes` reads `1 change` where {n} is 1. Its object is {branch}. Filed with `main`'s read where that gives a blueprint and `main`'s changelog holds rows of {time} or later, `time_after` counting inclusively, of any kind but a journal entry's, a branch's own, a webhook's and an event rule's, which no read reads, the last two the trigger's that `make netbox-hook` writes on `main`; a tag is counted, since a tag can be a scope; design/verified-facts.md, "A branch behind `main`" and "A rule's change is counted as a change of `main`".) |
