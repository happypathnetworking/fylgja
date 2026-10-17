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

## A persistent series on the fixture branch

**Raised** 2026-10-07, in the launch's clarify session, and parked by its spec (Out of
scope). **When**: in the order after the launch. **Status**: closed by
`014-proposed-change-stages` on 2026-10-17.

### The idea

Give `fylgja-fixture` a series of M10's marks of its own, written by its seed and kept, so
that a twin could be created from a mark and stepped without a throwaway branch and series
made around each run. The README's stepping walk-through, and the recording made from it,
seeded `fylgja-test-readme` and its series first and deleted both after, for want of one.

### Why it closed

[D-045](decisions.md#d-045) replaced the series with a proposed change's stages: one
proposed change, one story, with no series to keep. 014's spec gives `fylgja-fixture` no
proposed change, and the fixture tool refuses `-propose` and `-stage` on it, as it refused
a series (FR-026). The objection this entry recorded holds for a proposed change too:
marks follow writes, and the fixture's head is what tier 2 and tier 3's first case read
and compare with `testdata/ctm/three-node.json`, so it would move unless every change were
undone, and generated again, after its mark.

Of the two gains it named, the first came with the stages: tier 3's case 7 now steps an
SR Linux-only twin twice, to a mark and to the head, so a host without the cEOS tar,
narrowed to `PLATFORMS=nokia_srlinux`, steps a twin. The second did not: the stepping
walk-through still seeds its own throwaway branch and deletes it after, its stages and
proposed change first, and
`fylgja stage list` printing `no open proposed change` after a tier is how a run is seen
to have cleaned up.

## A webhook that starts a proposed-change check early

**Raised** 2026-09-14 in [D-026](decisions.md#d-026), as the candidate next step once
Fylgja ran a long-lived listener; carried as roadmap feature 9 until 2026-10-16.
**When**: not planned. **Status**: dropped from the roadmap, kept here.

### The idea

Once `fylgja serve` listens, a webhook from Infrahub starts a check early, adding to the
interval and never replacing the compare, so following's latency falls from the interval
to seconds. D-026 names it and keeps the compare whether or not it is built.

### Why it was dropped

Infrahub 1.11.2 runs a proposed change's checks at its creation and on a retry, not on a
branch update (the 014 probe, 2026-10-16), so a webhook adds nothing to a check posted on
a proposed change, which is what 0.2 builds. It returns to the roadmap if following's
latency matters to a consumer, or if Infrahub fires on a branch update.
