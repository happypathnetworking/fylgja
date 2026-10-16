# Specify brief: 0.2 feature 1 of 2: the proposed change rehearsed

This is what `/speckit-specify` reads for roadmap items 7 and 8, reshaped as one pass by
the roadmap's [Next section](../../docs/roadmap.md#next). It was written on 2026-10-16
from a design session with the operator. The session settled the direction of 0.2 and
every choice under [Decided](#decided). It read Infrahub 1.11.2's source and schema, and
the documentation, but verified nothing live: [Infrahub as read](#infrahub-as-read)
records what the session found, and the plan verifies each point before relying on it.
Specify what the operator gets, not a new design. [References](#references) names every
file to read.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/014-proposed-change-rehearsal. 0.2, the first of its two features: a proposed change rehearsed on a twin, as docs/roadmap.md's Next section and items 7 and 8 define it. Read specs/014-proposed-change-rehearsal/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Where the shape is fixed

- **The roadmap's [Next section](../../docs/roadmap.md#next)**, and items 7 and 8 with
  their 0.2 paragraph. This feature is 0.2's frame: the demo the release records happens on
  a proposed change. Probes, item 14, are the [next feature](../015-probes/brief.md), so
  this feature's gate has no loss in it.
- **[D-032](../../docs/decisions.md#d-032)**: a waypoint is a name for a pinned
  reference, written by the operator and only read by Fylgja. An absent `as_of` is the
  waypoint's own write stamp. **[D-036](../../docs/decisions.md#d-036)**: a step goes to
  another waypoint of the twin's own series (`step.target.foreign`); a failed step leaves
  the twin up and diverged.
- **[D-038](../../docs/decisions.md#d-038)**: verify's assertions are derived from the
  bundle. **[D-039](../../docs/decisions.md#d-039)**: verify is advisory, and no Fylgja
  operation reads its report. A client may.
- **[D-026](../../docs/decisions.md#d-026)** and the roadmap's item 7: Fylgja never writes
  to Infrahub; the check writes its own result.
- **[D-040](../../docs/decisions.md#d-040)–[D-042](../../docs/decisions.md#d-042)**: every
  command goes through `fylgja serve`. One bearer token, in the clear, on loopback unless
  `--listen` says otherwise. D-042's revisit clause names "the check inside Infrahub".
- **[D-044](../../docs/decisions.md#d-044)**: this repository is registered read-only on
  `main`. A change to its Infrahub files reaches Infrahub only when imported from
  `origin`'s `main`.
- **[Constitution 1.1.1](../../.specify/memory/constitution.md)**:
  - **I**: Go end to end. The check's Python is Infrahub's runtime, as the Jinja template
    is, and it stays glue ([Decided](#decided)).
  - **III**: every operation Fylgja makes on Infrahub is a query.
  - **VI**: Fylgja sends no `at` of its own.
  - **VII**: one twin at a time.
  - **X**: no credential in anything written, and the honesty of every report.

<a id="infrahub-as-read"></a>
## Infrahub as read, 2026-10-16 (from the 1.11.2 source and schema, unverified live)

- **The pipeline runs on two occasions only**: when a proposed change is created, and on
  `CoreProposedChangeRunCheck`, the UI's retry (`check_type` all or user). It does not run
  when the branch is updated.
  - Only one open proposed change is allowed per source branch.
  - The destination must be `main`.
  - A read-only repository's check definitions run.
- **A global check runs once.** It is given its worktree, the **source branch** as
  `branch_name`, and an authenticated client. It is given neither the proposed change's id
  nor the destination. The SDK's `proposed_change_id` is never filled.
- **The timeout is the check class's `timeout` attribute**, default 60s, applied as a
  Prefect task timeout. What a timed-out check leaves behind is unknown.
- **The result.** It is one `CoreStandardCheck` per run. Its message is the log entries as
  plain text, shown in a monospace viewer inside a collapsed "Message". Severity is `info`
  or `critical`. A check that called `log_error` has failed.
- **Every validator but the data validator must conclude `success` before a merge**,
  including one still running. There is no advisory flag, and Community enforces it.
- **Comments render markdown.** `CoreChangeComment` (`text`) and the description render
  GitHub-flavoured markdown and Mermaid. A check's messages do not.
- **No secret reaches a check by Infrahub's means.** The task worker's environment is the
  way.
  - The task workers (two replicas) are on the Compose bridge.
  - `host.docker.internal` does not resolve there, and `127.0.0.1:7650` is not the host.
- **There is no `proposed_change.created` event.** `infrahub.node.created` filtered to the
  kind stands in, and `infrahub.validator.{started,passed,failed}` exist.
- The [public reachability-check demo](https://github.com/opsmill/infrahub-demo-reachability-check)
  is the nearest thing OpsMill shows, and the
  [`infrahub-managing-checks` skill](https://github.com/opsmill/infrahub-skills) is
  theirs.

## What changes, and nothing else

1. **`fylgja twin rehearse --series <s>`**, and the API operation `twin.rehearse`. A run:
   - creates the twin from the series' first waypoint and verifies it (the baseline);
   - steps through each later waypoint in sequence order, with the step's wait, verifying
     after each;
   - stops at the first stage that fails;
   - always destroys the twin;
   - answers with a **rehearsal report**.

   A stage **fails** when its step leaves the twin diverged, or when verify finds what the
   baseline did not. The baseline's own findings are reported and never fail a stage. The
   report is a document of its own, with a JSON schema in `contracts/`, and renders as
   text and as markdown. The markdown holds a table with one row per stage, a Mermaid
   drawing of what each stage changed, the fidelity caveat, and, on a failure, the commands
   that reproduce it.
2. **The stage list as a read**: an operation that, given a branch, returns the
   rehearsal's stages as pinned references, with its warnings.
   - The first stage is the branch at its branch point (`branched_from`).
   - Then each waypoint of the one operator series whose waypoints all name the branch,
     in sequence order.
   - Then the branch's head, unless the step to it is `unchanged`.
   - It warns when `main` has moved since the branch point.
   - It refuses when more than one series names the branch, naming them.

   Fylgja reads, as everywhere; it writes nothing.
3. **Two checks in this repository**, global, as `InfrahubCheck` classes in `.infrahub.yml`.
   Each finds its proposed change by the source branch, asks Fylgja for the stage list,
   and writes the stages as its own series.
   - **`fylgja-step`** asks for `waypoint plan` over its series, logs it as plain text and
     deletes its series. It fails only when Fylgja refuses a stage as intent, refuses the
     stage list, or cannot be reached.
   - **`fylgja-twin`** asks for `twin rehearse` over its series. It posts the report's
     markdown as a comment and logs its text. It concludes failure when a stage failed or
     the rehearsal could not run. It deletes its series on a pass and keeps it on a
     failure.
   - A comment that cannot be posted is logged and does not fail the check.
4. **Reclaiming a dead rehearsal**: a rehearsal that finds a twin left by a rehearsal whose
   run is no longer running destroys it before it starts. Any other twin is refused, under
   VII, as now.
5. **`fylgja serve --listen` is repeatable.** The start-up report names each address and,
   for each off loopback, that the token crosses it in the clear.
6. **Infrahub's Compose override** (`scripts/infrahub/docker-compose.override.yml`) gives
   the task workers a `host-gateway` entry, `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`.
   The bring-up script's parts start the server on loopback and on the bridge's address. A
   check whose variables are unset fails, saying so: CI's contract job runs no server.
7. **The records.**
   - `contracts/` (the API's operations, the report's schema, `cli.md`).
   - The architecture and its C4 model (the checks, `twin rehearse`, the bridge listener).
   - development.md (the three processes, the override, how the checks are tested).
   - verified-facts.md (everything under [Infrahub as read](#infrahub-as-read) that the
     plan verifies).
   - The glossary (rehearsal, stage, baseline finding).
   - `SECURITY.md` (the bridge listener's exposure).
   - The README (the proposed-change walk-through).
   - `CLAUDE.md`'s State.

<a id="decided"></a>
## Decided

- **The shape**: a twin per proposed change, torn down after, rather than a standing twin
  of `main` that each proposed change steps and steps back. That one waits for a later
  release.
- **The stages are the operator's waypoints on the source branch**, copied into the
  check's own series. With no operator series there are two stages, branch point and
  head.
- **The rehearsal starts at the branch point**, not at `main`'s head. Reading a stage of a
  branch that is behind `main` shows `main` as it was at the branch point, so a step from
  `main`'s head would also revert `main`'s later changes. When `main` has moved, the
  report warns and the rehearsal goes on.
- **The check writes the series and the comment; Fylgja only reads** (Constitution III).
  The series makes every stage a pinned waypoint, so `twin rehearse` is the M10–M12 path
  (create, step, verify) with no new kind of target, and Constitution VI holds: each `at`
  is an Infrahub stamp or one the check copies from the operator's waypoint.
- **Each check has its own series**, since the two run at the same time.
- **The rehearsal lives in Fylgja, as a workflow**, not in the check. The deadline,
  cleanup, reclaim, classification and report are Go and tested at tier 1. A cancelled
  check cancels the run. Rehearsing a series is a command outside proposed changes too.
- **The Python is glue.** It finds the proposed change, writes and deletes the series,
  calls the API, posts the comment and sets the conclusion. Everything that decides is in
  Go behind the API.
- **The gate.**
  - A stage fails on divergence or a finding not in the baseline. The rehearsal stops
    there.
  - The check fails on any failed stage, on a rehearsal that could not run, and on Fylgja
    unreachable.
  - The baseline's findings never fail anything.
  - Fylgja's report stays advisory: the check maps it to a conclusion
    ([D-039](../../docs/decisions.md#d-039)).
- **The report's rich form is a comment**, since a check's message renders as plain text.
  The message carries the same report in text.
- **The series is deleted on a pass and kept on a failure**, so that a failure is
  reproducible by hand with `twin create --waypoint` and `twin step`, which the report
  names.
- **The server listens on the host's Docker-bridge address, in plaintext, beside
  loopback.** The token stays on the host, but any container on the host can reach the
  address, the twin's own nodes included, and the bearer check is what guards it. A relay
  container and server TLS were rejected.
- **The checks wait.** A check's `timeout` is raised so that the twin finishes inside it.
  The rehearsal's own deadline sits short of that timeout, so cleanup always runs.
- **Out of this feature**: probes and loss (015), the webhook (item 9), the agent skill,
  the state diff and observation.

<a id="open"></a>
## Open, for clarify

1. **A twin that exists and is not a dead rehearsal.** Does `twin rehearse` refuse at
   once, so the check retries within its deadline, or does the rehearsal wait for the slot
   within its own deadline?
2. **A retry's series.** When a series kept from an earlier failure exists, a retried
   check either replaces it, or writes a new series with a run number (`pc-<id>-twin-2`).
3. **The deadline.** Is it fixed per check (one `timeout` long enough for a bounded number
   of stages, with longer series refused up front), or derived from the stage count with a
   ceiling?
4. **The markdown's form.** A third `render` value beside `text` and `json`, or a field of
   the report's JSON that the check posts as it is.

## Left to the plan

- **Live verification on a throwaway proposed change** (`fylgja-test-*`), recorded in
  research.md and then verified-facts.md:
  - how a long multi-line message renders;
  - what a timed-out check leaves behind (validator state, conclusion);
  - whether the task worker's client may create a `CoreChangeComment`;
  - whether a check runs on a proposed change that changes only data;
  - what a read pinned at exactly `branched_from` returns (the decision log's open question
    on reads before a branch existed);
  - how a branch's being behind `main` is read.
- **How the checks are tested before they are on `origin`'s `main`**, since the
  registration imports only from there. Perhaps a second, test-only registration. Also:
  the tier-2 run of `fylgja-step` needs a server the task workers reach, and CI's contract
  job runs none. Does CI start one, or does that test skip there and say so?
- **The workflow's shape**: child workflows of provision, step, verify and destroy, or one
  workflow with their activities; its fixed id under VII; how it is cancelled.
- **The API's answer for a run of minutes** inside Infrahub's timeout, and the check's
  client for it: Python against the API's frames.
- **The decision entries** the roadmap names for 014, written after the verification.
- **Load OpsMill's `infrahub-managing-checks` skill** before writing the checks
  (`/plugin marketplace add opsmill/claude-marketplace`, `/plugin install infrahub@opsmill`).

## Exit

- **Tier 1**: the stage list, the classification against the baseline, the report and its
  renderings, the deadline and the reclaim, with the rehearse workflow under Temporal's
  test suite.
- **Tier 2**: on a throwaway branch with a two-stage operator series, a throwaway proposed
  change runs `fylgja-step` to a pass, and to a failure on a stage Fylgja refuses. The
  stage-list read, with its refusal and its warning, runs against the real Infrahub. No
  twin, as always in tier 2.
- **Tier 3**: a new case. A proposed change with a two-stage operator series is rehearsed
  through `fylgja-twin`, which passes, posts its comment and deletes its series. A stage
  that fails, by a means the plan chooses, fails the check at that stage and keeps the
  series. After it, no twin and no `fylgja-test-*` series remain.
- **Owed before the work starts**: OpsMill's skills installed. Nothing else.

<a id="references"></a>
## References

Read in this order, after `CLAUDE.md`'s list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Next](../../docs/roadmap.md#next), items 7, 8 and their 0.2 paragraph, [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope and the decisions owed |
| [docs/decisions.md](../../docs/decisions.md): D-026, D-032, D-036, D-038, D-039, D-040–D-042, D-044, the [open questions](../../docs/decisions.md#open-questions) | what this feature builds on and supersedes; numbering continues from D-044 |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) 1.1.1: I, III, VI, VII, X | the Constitution Check |
| [contracts/api.md](../../contracts/api.md), [contracts/step.schema.json](../../contracts/step.schema.json), [contracts/verify.schema.json](../../contracts/verify.schema.json), [contracts/waypoints.schema.json](../../contracts/waypoints.schema.json) | the operations rehearse composes and the documents its report draws on |
| [schema/fylgja-waypoint.yaml](../../schema/fylgja-waypoint.yaml), [schema/README.md](../../schema/README.md) | the kind the check writes |
| [.infrahub.yml](../../.infrahub.yml), [infrahub/](../../infrahub/), [scripts/infrahub/docker-compose.override.yml](../../scripts/infrahub/docker-compose.override.yml) | where the checks and the task workers' variables go |
| [docs/architecture.md](../../docs/architecture.md) §4.6, §6; [docs/c4/workspace.dsl](../../docs/c4/workspace.dsl) | the API's place, and the drawing to redraw |
| [internal/step](../../internal/step), [internal/verify](../../internal/verify), [internal/waypoint](../../internal/waypoint), [internal/server](../../internal/server) | what rehearse composes |
| [docs/verified-facts.md](../../docs/verified-facts.md): Infrahub 1.11.2 | what is already verified of the reads |
