# Fylgja — How it was built

Fylgja was built by Claude, an AI agent, working through the
[Spec Kit](https://github.com/github/spec-kit) workflow, with a human deciding every
question of scope and design. This page says what that workflow is, what its passes found,
and what its hours say. The record it summarises is private ([below](#what-stays-private)).

## What Fylgja is

Fylgja builds a walking twin of a network from its intent: an Infrahub branch, and
optionally a point in time, compiled by a pure compiler into a deterministic bundle and
booted as one containerlab topology on real network operating system images, with each
device's configuration as Infrahub rendered it. Provisioning runs through Temporal, there
is no database, and every command is a request to the API's server on the lab host. The
[brief](brief.md) says what it is for, and the [roadmap](roadmap.md) what each milestone
delivered.

## What a Spec Kit pass is

A **pass** is one run of one Spec Kit command, and each milestone is a feature taken
through them in order:

1. **specify** writes the specification from a short prompt that carries the human's
   decisions, and **clarify** asks the human at most five questions and writes the answers
   into it.
2. **plan** designs against the running systems and checks the design against the
   constitution; **tasks** breaks it into a dependency-ordered task list; **analyze** reads
   the specification, plan and tasks against each other for gaps and conflicts.
3. **implement** builds the tasks, in several runs when a feature is large or has a stop
   only the human can pass: a first run against real infrastructure, a twin to boot, a
   golden file to review.
4. **converge** reads the code against the specification and appends what is still
   unbuilt, which the next implement builds. It repeats until the stopping rule is met.

Every pass but clarify starts in a fresh context and reads its inputs from disk, so the
documents carry the project from one pass to the next, not a conversation. The human writes
each specify prompt, answers each clarify question, reads each pass's report, commits by
hand, runs what only an operator can, and records a changed decision in the
[decision log](decisions.md) before the code follows it. The workflow, the model and
effort each command runs on, and the converge loop that runs the later passes unattended
are in [development.md](development.md#spec-kit-workflow).

## What a convergence pass finds

Implementation is never the last word on a feature: a convergence pass finds what the
first build left out. It appends tasks, each tagged since M10:

- **`[behaviour]`**: the code does not yet do what the specification says, and the task
  changes what it does.
- **`[pin]`**: the behaviour is right but unguarded; the task adds a test, a line of
  documentation or a named constant, and leaves the code under test unchanged.
- **`[operator]`**: the task needs the human, a decision or a run on the host that no
  unattended session may make.

Convergence ends after two passes in a row that change no behaviour, or one pass that
appends nothing. Across M1–M13 and the cut, 72 convergence passes appended 199 tasks
(M1 and M2 not counted, since their log predates the count). From M10, where the tags
begin, the task lists carry 38 `[behaviour]` tasks and 95 `[pin]` tasks.

## The figures

Every figure here is **derived from the private record** of M1–M13 and the cut, counted
in one session on the development host by a script that printed numbers alone, and read
by the operator before it was committed. Hours are the command log's active time, each
command and its follow-ups, with every wait on the human left out. A pass is one logged
Spec Kit command. Model time is active time by model; a command that ran on two models is
split by its share of responses. Each figure is rounded on its own, so a column need not
sum to its total. The launch, the first feature built in this repository, is not in them.

| Milestone | Features | Hours | Passes | Convergence passes | Fable 5.1 h | Opus 5 h | Opus 5.5 h |
|---|--:|--:|--:|--:|--:|--:|--:|
| before M1 (the constitution) | — | 0.4 | 1 | — | 0.4 | — | — |
| M1 — Read and compile | 1 | 2.9 | 17 | 3 | 0.8 | 2.1 | — |
| M2 — Provision and destroy | 1 | 7.7 | 34 | 11 | 2.2 | 5.5 | — |
| M3 — Operate | 1 | 2.4 | 11 | 1 | 0.5 | 1.9 | — |
| M4 — Walking | 1 | 7.0 | 34 | 12 | 0.5 | 6.5 | — |
| M5 — Configuration | 1 | 5.3 | 25 | 8 | 2.3 | 3.0 | — |
| M6 — PSP format and lossy mapping | 1 | 3.8 | 17 | 3 | 1.1 | 2.7 | — |
| M7 — EOS | 1 | 11.2 | 20 | 3 | 2.4 | 8.7 | — |
| M10 — Waypoints | 1 | 6.3 | 21 | 5 | 1.7 | — | 4.6 |
| M11 — Stepping | 1 | 13.4 | 46 | 13 | 1.3 | — | 12.1 |
| M12 — Verify | 1 | 7.8 | 25 | 5 | 0.9 | — | 6.9 |
| M13 — API | 1 | 12.4 | 39 | 8 | 0.8 | — | 11.6 |
| M14 — the cut | 1 | 4.8 | 19 | 0 | 1.1 | — | 3.7 |
| **all** | **12** | **85.4** | **309** | **72** | **16.1** | **30.6** | **38.8** |

By command, the 309 passes were 13 specify, 13 clarify, 12 plan, 12 tasks, 16 analyze,
169 implement, 72 converge and 2 constitution (its ratification and one amendment). The
twelve features hold 947 tasks in all; the private history holds 809 commits through the
cut; the decision log held 44 entries and the verified-facts record 80 at the cut. Sonnet
5.5 and Haiku 4.5 ran only as subagents, inside a command's time, so they add no hours.
All models together took about 3.9 billion input tokens, most of them cache reads, and
wrote about 18.3 million.

## What the hours say

- **The agent's working time is small and countable.** Eleven milestones and the cut took
  85.4 hours of active agent time, about seven a feature, counted per pass. That made two
  choices measurable rather than argued: which model runs which command, priced against
  judgement, and when convergence stops.
- **It is many short passes, not one long run.** 309 passes, each starting cold from the
  documents on disk, so a pass that goes wrong is one pass to redo, and every handover
  is something the human can read.
- **Convergence is about a quarter of the passes, and its tail is mostly guards.** 72 of
  the 309 passes were convergence, and from M10 the task lists carry more than twice as
  many `[pin]` tasks as `[behaviour]` ones: once the behaviour is right, what a pass adds
  is a test or a line of documentation, which is what the stopping rule counts on.
- **The largest milestones were stepping (M11) and the API (M13)**: they took the most
  hours and their convergence appended the most tasks.
- **The hours are the agent's, not the project's.** The human's time — writing each
  prompt, answering each question, reading each report, deciding, and running what only
  an operator can — is not in the record and is not claimed. The figures say what the
  agent cost with a human deciding; they do not say what the agent would cost without one.

## What stays private

The record of how M1–M13 and the cut were built stays private: the history, each
feature's specification, plan, research log and tasks, the command log of every session,
and the earlier forms of the decision log and the roadmap. They are records of how the
project was built, not documents a reader needs to understand or stand up what was built;
they cite commit hashes, process ids and local paths, and publishing them would mean
auditing every commit for what it carried. So this repository began as one commit of
cleaned code and rewritten documents, and development continues here
([D-043](decisions.md#d-043)). This page summarises that record and cites none of it. The
features specified in this repository, beginning with the launch, are in
[`specs/`](../specs/), with their research and tasks.
