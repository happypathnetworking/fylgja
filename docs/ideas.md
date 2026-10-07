# Ideas for refining development

Ideas for changing how Fylgja is developed, kept until one is taken up or dropped. An
entry is not a decision: nothing here binds a plan, and a change to the process still
lands in `docs/development.md`, with an entry in `docs/decisions.md` where it reverses
one.

Each entry says what the idea is, when it was raised, what is already known about it,
and what would have to be checked before building it.

## A directing agent over the Spec Kit workflow

**Raised** 2026-10-04 by the operator. **When**: after Fylgja is launched (M14).
**Status**: open.

### The idea

Make the process more automated. One primary agent holds an initial conversation with
the operator to define a feature's requirements, then spawns subagents that execute the
workflow (`plan` → `tasks` → `analyze` → `implement` → `converge`).

### Assessment (2026-10-04)

Reasonable, and the process is most of the way there:

- Each Spec Kit command already runs in a fresh context and reads its inputs from disk,
  so the tree is the handoff and little is lost between agents.
- `specify` and `clarify` already share one context. That is the requirements
  conversation.
- The attended converge loop (`/converge-loop`) already has a session that starts the
  work and relays the loop's questions to the operator.

So the shape to aim for is the attended loop extended backwards: one conversational
session for requirements and questions, with a script driving `plan` through `converge`
beneath it.

Four adjustments to the idea as stated:

- **The primary agent converses; it does not direct by judgment.** A script or workflow
  owns the order of commands, the stopping rule and the commits, as
  `scripts/converge-loop.sh` does. A model directing a long run fills its context,
  drifts, and tends to believe its subagents' reports.
- **Each stage is gated on the tree, not on a report.** Tier 1, lint, the static check
  and the convergence count decide whether a stage passed.
- **Questions arrive mid-run, not only at the start.** A convergence pass can raise an
  `[operator]` task long after the spec was settled, so the primary agent stays
  available as the relay for the whole run.
- **The gain is unattended hours, not parallelism.** The pipeline is sequential, the
  agents commit to one tree, and the host runs one twin at a time.

### To check before building

- Whether the command-log hooks record an in-session subagent as its own entry, with
  its model, effort and timings. The log is the only record of a session's model, effort
  and time; headless sessions started by a script are logged.
- Whether a subagent can be given the model and effort that `docs/development.md`'s
  table assigns to each command.
- How the live stages (tier 3, the worker, the hand scenarios) are serialised, and
  which sessions are given the node logins.
