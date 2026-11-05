---
name: build-phase
description: Use when starting, designing, planning, executing or landing a phase of fylgja-core (an item of design/core.md's "Sequence", such as "phase 6"). Gives the lifecycle, the branch, worktree and file names, what every implementer and reviewer is handed, and how a phase lands, so that no earlier phase's records need reading first.
---

# Building a phase of fylgja-core

A phase is one item of the "Sequence" in `design/core.md`. It moves through the project's one
process (a design document, a decision entry where a decision changes, then pull requests;
D-033) in four stages: settle, plan, execute, land. `CONTRIBUTING.md`, "How a phase is
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
- Plans drafted side by side are reconciled where they meet, and plan 0 gains a section
  saying what was settled.
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

  The ledger, not the session's memory, says what is done.
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
- **A plan ends** with one review of its whole branch on the most capable model, one fix
  wave, and one check of that wave. Then its commits' trailers are made uniform, it is merged
  into the integration branch (`--no-ff`), and the next plan's branch is cut.
- **The controller rules and goes on.** It stops for four things alone: an operation that
  cannot be undone, a security-sensitive action, a side effect outside the phase's own
  branches that one asks about first (a merge into `main`, a push), and a plan so broken that
  every way forward is a guess.

## 4. Land

Only on the maintainer's word.

1. When every plan is merged and the phase's "done when" holds, tell the maintainer, with
   every ruling made on their behalf and what each costs if wrong.
2. Squash the integration branch onto `main` as one commit, `feat: phase N, <what it built>`,
   its body saying why.
3. Tag the integration branch `archive/phase-N-integration`, so the hashes the ledgers name
   still resolve.
4. Copy each plan's workspace to `local/sdd/phase-N/<plan>/`, and the collected rulings to
   `local/sdd/phase-N/rulings.md`.
5. Remove the worktrees and the phase's branches. Never push unless asked.
6. In `design/core.md`, mark the item of "Sequence" done, with its date, what it built and
   what it left to later phases.
7. Amend this file, `house-rules.md` and `CONTRIBUTING.md` with whatever the phase taught.
