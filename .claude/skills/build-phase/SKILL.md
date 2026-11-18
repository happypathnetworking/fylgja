---
name: build-phase
description: Use when starting, designing, planning, executing or landing a phase of fylgja-core (an item of design/core.md's "Sequence", such as "phase 6"). Gives the lifecycle, the branch, worktree and file names, what every implementer and reviewer is handed, and how a phase lands, so that no earlier phase's records need reading first.
---

# Building a phase of fylgja-core

A phase is one item of the "Sequence" in `design/core.md`. It moves through the project's one
process (a design document, a decision entry where a decision changes, then pull requests;
D-033, and D-080 for a phase) in four stages: settle, plan, execute, land. `CONTRIBUTING.md`, "How a phase is
built", states the same for people; where the two disagree, that section is right and this
file is corrected.

Where the superpowers plugin is installed, its skills carry the generic steps: brainstorming
for stage 1, writing-plans for stage 2, subagent-driven-development for stage 3,
finishing-a-development-branch for stage 4. This file is what the project fixes on top of
them. Without the plugin, follow the stages as written here.

## Before anything

- Read what `AGENTS.md` lists under "Read first". They bind every stage.
- **Never write on `main`.** Cut the stage's branch before the first edit, a design document
  included.
- **Site values are never in the tree**: cluster access, a registry's address, logins.
  They live in `local/` (git-ignored, in the main checkout only) and in the maintainer's own
  notes. Ask where they are; never copy one into a tracked file.

## 1. Settle the design

Branch `phase-N-design`, cut from `main`.

1. **Ask the maintainer what done looks like**, play back what you understood, and find out
   which of the open choices they want to make themselves. Research the rest and bring
   options with a recommendation.
2. **Read the running systems first.** A decision that asserts how a runtime, a library or a
   service behaves is written only after that behaviour was read. Record each reading in
   `design/verified-facts.md` with its version and date, and commit the facts on their own
   (`docs(facts): …`). Remove whatever the reading started.
3. **Write the phase's section** in `design/core.md`, before "## Sequence":
   `## Phase N: <what it is> (settled YYYY-MM-DD)`. It has the parts the earlier phases'
   sections have, in their order:
   - what the phase is for;
   - what is settled before code, one bullet a decision, each citing its entry;
   - the formats touched;
   - non-goals, and anti-goals (each a failure even if the code works);
   - the plans, numbered, "each a branch and a pull request useful on its own", and which
     may run side by side;
   - "The phase is done when …";
   - what is left to the builder.

   Mark the item in "Sequence" as settled, with the date.
4. **Write the decision entries**, each at the next free number, at the end of its topic's
   section of `design/decisions.md`, with its index row. Give every entry it supersedes or
   adds to a status note; the old entry's text stays. Read the rejected alternatives first.
   A design branch cut before the previous phase lands takes its numbers provisionally:
   that landing takes the next free numbers on its own integration branch, and this design
   renumbers when it is rebased onto `main`.
5. **Search `design/architecture.md` and `design/core.md`** for every sentence the new
   entries make untrue, and correct it.
6. **Have a fresh reader check the draft.** A subagent given only the documents and the code
   reads the section as someone who must plan from it, and reports where it would have to
   guess and where the draft contradicts the code, an earlier decision or a recorded fact.
   Settle each: answer it in the documents, make the call and say so, or take it to the
   maintainer.
7. **Gates and commit**: `make lint`, `make test`, `make linkcheck`; then
   `docs(design): phase N settled, …`. Hand the maintainer the section with the list of calls
   you made that they did not weigh. **No plan is written before they approve it.**

## 2. Plan

Plans are working documents under `local/plans/`, git-ignored, named for the day they were
written.

- **Plan 0**, `YYYY-MM-DD-phaseN-0-branches.md`, from `plan-0-template.md` beside this file:
  the branches, the order, the live-tier rule, and **the names the plans share**: every
  name and signature a later plan relies on from an earlier one. An implementer sees one
  task; plan 0 is how plans agree.
- **One plan for each of the design's plans**, `YYYY-MM-DD-phaseN-<n>-<name>.md`:
  - a header: Goal, Architecture, Tech Stack, Spec (the design section, the decisions, the
    facts);
  - **Global Constraints**: what binds every task, with exact values;
  - **Review Focus**: the inputs and failures the design implies and no task's happy path
    exercises, each pinned by a test in the task that owns the code;
  - tasks, each with its Files (create, modify, test), its Interfaces (what it consumes and
    produces, as exact signatures), checkbox steps (the failing tests named with their
    assertions, then the code, then the gates), and its commit message with a body that says
    why.
- A plan is 100 to 250 dense lines. It fixes names, values and tests, and writes no code a
  test already determines.
- **A step that rests on behaviour not yet read** on a running system begins with the
  reading, and says what the task does if the reading differs.
- **A reading the design leaves to a plan goes to a test whose path runs the code read.**
  Trace it before the plan is written: a live test that drives the driver alone never
  pushes, so it cannot read what pushing does (phase 7 moved such a reading a plan later).
- **Before a step names a tool, read the rules its file is held to.** A conformance
  scenario starts no process, by the suite's own pure check; a step that has it run a
  command cannot be built as written.
- Plans drafted side by side are reconciled where they meet, and plan 0 gains a section
  saying what was settled.
- **A criterion that says the maintainer has watched says how.** The plan names who runs the
  command and where its output shows: the maintainer runs it, or the controller shows its
  whole output before the next act. Phase 9's first run was built with the output in a log,
  and whether it had been watched had to be asked afterwards.
- **A bound a runbook states as a rule says what it is there to tell.** "A run with no
  validator 120 s after the creation is not the run" told a check that never starts; a run
  that passed 11 s later had to be ruled on, and the ruling got the bound's origin wrong.
- **Plan 0 keeps the bends.** Each place a plan, or later a ruling, departs from a
  decision's text is added to plan 0 when it is made, with the entry it bends. The landing
  writes its decision entries from that list.
- The maintainer reviews the plans and chooses how they are executed.

## 3. Execute

- **The integration branch** is `phase-N-integration`, cut from `main` with the design branch
  merged in first (`--no-ff`).
- **Each plan** gets the branch `phase-N/<n>-<name>`, cut from the integration branch when it
  starts, in a worktree beside the repository, `../fylgja-core-wt/<n>-<name>`. Run
  `make venv` there, then a baseline `make test`, in the foreground.
- **The controller**, the session running the phase, keeps a workspace for each plan outside
  the tracked tree (`.superpowers/sdd/<plan>/` with the plugin). It holds:
  - `progress.md`, the ledger: its first line names the plan; then the pre-flight scan (a
    row for every pair of tasks that share a file or an interface, and one for every task
    against itself); every decision taken on the maintainer's behalf, as
    `Ruling: <what> — <why> — <what it costs if wrong>`; deferred minor findings; and
    `Task N: complete (commits a..b, …)`;
  - each task's brief (the task's text, extracted from the plan), its report, and the diff
    its reviewer read.

  The ledger, not the session's memory, says what is done. An item ruled "for the landing"
  goes into plan 0's bends or the ledger's "For the landing" list as it is ruled, never only
  into the ruling's text: the landing's brief is written from those lists.
- **Every implementer and reviewer is handed** `house-rules.md` (beside this file), the
  task's brief, the plan's Global Constraints and Review Focus, and a report file. Never the
  whole plan, and never the session's history.
- **One implementer at a time in a worktree.** Plans in different worktrees may run side by
  side.
- **After each task**, a fresh reviewer reads the task's diff: first whether it is what the
  brief asked, then whether it is well built. Findings go back to the implementer, for at
  most five rounds; what is still open then, the controller rules on and records. The
  controller never mends code itself.
- **When a task is ledgered complete, the controller ticks its boxes in the plan.** The
  implementers cannot: the plan is not in their tree.
- **Live runs are one at a time**: the local live tier in one worktree, the cluster's tests
  for one plan, and never both together where they share hardware. The controller says
  whose turn it is.
- **A plan whose cluster run needs the phase's core** gets it from the controller: the
  integration branch's image built, pushed and deployed before that plan's window, its tag
  in the ledger. Two cores never run on the cluster: the deployed one is scaled to nothing
  before a test starts its own.
- **A fix that changes a test run live is followed by one run of that test**, so that the
  merged code has run; where no window allows it, the landing says at which commit the
  facts were read.
- **A live run made from the main checkout runs the main checkout's code.** `local/` is
  there alone, and the `make` targets run the working directory's scripts and venv. For a
  plan's live run the main checkout is checked out detached at the code under test, the
  ledger says so, and it goes back on the integration branch when the runs are over.
- **A task off the live window may run in a worktree of its own** beside the one that holds
  it (a runbook, the documents, a fix wave while a contract tier reads the plan's worktree),
  its branch merged by the controller. Once the plan's trailers are made uniform such a
  branch is no ancestor of the archive tag: the tag made before the rewrite holds it, and
  it is removed when a commit of the same tree stands in the rewritten history.
- **What a fact cites is in a file of its run's directory** before the task is reviewed. A
  script a later task reuses is kept in the plan's workspace under its task's name: phase
  9's scratch reader of one run was overwritten by the next task's.
- **A fact is a reading.** A reviewer is asked whether each new fact says only what its run
  showed. A figure worked out from others is called a derivation, and whether a bound or a
  wider wait is needed is a ruling, recorded in the ledger and entered at the landing.
- **A time budget a live test rests on is a reading too**, and readings of a shared system
  drift: phase 8 sized a deadline from one run of Infrahub's reads, which doubled in two
  days, and it failed later on the same code. The test's docstring names the readings it
  rests on and the budget's ratio to the slowest; the closing gate's run is read against them.
- **The maintainer's word on an acceptance run names what they read.** Its runbook asks them
  to say they read the report in its thread, not only that the run passed.
- **A plan ends** with one review of its whole branch on the most capable model, one fix
  wave, and one check of that wave. The last plan's reviewer is also asked for every line
  of the design documents the phase has made untrue. Where the last record of a run waits on
  the maintainer, the review starts without it: that record gets its task review, and the
  check of the fix wave reads it. Then the plan's commits' trailers are made uniform, it is
  merged into the integration branch (`--no-ff`), and the next plan's branch is cut.
- **A reason the controller gives for a ruling is checked against the tree** before it is
  written or told. What a ruling costs if wrong is the controller's to judge; what the tree
  says is not.
- **The controller rules and goes on.** It stops for four things alone: an operation that
  cannot be undone, a security-sensitive action, a side effect outside the phase's own
  branches that one asks about first (a merge into `main`, a push), and a plan so broken that
  every way forward is a guess.

## 4. Land

Only on the maintainer's word.

1. When every plan is merged and the phase's "done when" holds, tell the maintainer, with
   every ruling made on their behalf and what each costs if wrong.
2. **Write the phase as built**, in one gated commit on the integration branch
   (`docs(design): phase N as built, …`), so that the squash carries it:
   - a decision entry for the bends of each topic ("… as built"), from plan 0's list and the
     ledgers' rulings, with its index row and a status note on every entry it supersedes in
     part;
   - every line of `design/core.md`, `design/architecture.md` and
     `design/verified-facts.md` the phase made untrue, corrected;
   - a line of `design/decisions.md`'s preface the phase made untrue, corrected: the preface
     is conventions, not an entry, and append-only binds the entries;
   - the item of "Sequence" marked done, with its date, what it built and what it left to
     later phases; what it left unanswered goes under "Open questions".

   Before the tag, the as-built commit gets a review on the most capable model, one fix wave
   and one re-review, as a plan's last review does. The reviewer is a fresh one, or the one
   who compiled the last list of design lines, who holds what the commit was written from.
   The wave amends the commit, so the phase as built stays one commit, and the re-review is
   made before the squash: phase 9's was made after it.
3. Tag the integration branch `archive/phase-N-integration`, so the hashes the ledgers name
   still resolve.
4. Squash the integration branch onto `main` as one commit, `feat: phase N, <what it built>`,
   its body saying why, what was verified and what was not run. The squash's tree is the
   gated one: `git diff main phase-N-integration` prints nothing.
5. Copy each plan's workspace to `local/sdd/phase-N/<plan>/`, the collected rulings to
   `local/sdd/phase-N/rulings.md`, and the logs of the runs the facts were read from.
6. Remove the worktrees and the phase's branches, once each branch is an ancestor of the
   tag (`git merge-base --is-ancestor`), with `git branch -D`: `-d` refuses, since a squash
   is no merge. Never push unless asked.
7. Amend this file, `house-rules.md` and `CONTRIBUTING.md` with whatever the phase taught.
