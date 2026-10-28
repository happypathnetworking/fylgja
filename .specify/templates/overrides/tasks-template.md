---

description: "Task list template: this repository's override of Spec Kit's (docs/development.md, Spec Kit workflow). A section list with the rules each section follows; never a form to fill."
---

# Tasks: [FEATURE NAME]

**Input**: the design documents under `specs/[NNN-slug]/`: plan.md, spec.md, research.md,
data-model.md, contracts/, quickstart.md, the brief, and the decision entries they cite.

**Tests**: name each tier's cases from the brief's Exit, the spec's success criteria and
quickstart; each is a task. Say what must not move (a golden, a fixture id).

**Organization**: the plan's "Order of the work". Each phase leaves the tree green, since
the loop runs the pure gates (`make build`, static, `make test`, `make lint`) after every
run.

**Already done before this file**: what the brief's Exit owed and the plan did (the
roadmap's edits, the decision entry, the operator steps ticked in the brief).

**Decisions this file takes, against or beyond the plan's text**: one bullet each, for
`analyze` to settle. Leave the heading out when there are none.

**Tags**: `[operator]` marks a task that needs the operator and could not be done before
the chain: the review, a push, an import that waits on the pushed tree. Keep them to a
minimum; each carries its reason in one clause on its line, "since …" or "because …",
which the chain's tasks gate greps, and sits at the latest point its dependents allow. Everything an operator could settle before `specify` is the brief's,
not a task. `[live]` marks a task that needs the development host's server or worker
restarted from this tree, a twin, a hand scenario, the whole contract tier beside the
server on the bridge, or the end-to-end tier. A single tier-2 test a task names is not
`[live]`: the loop's sessions hold Infrahub's address and token and run it. A loop run
commits its own work; a hand run leaves it for the operator to commit. A session never
pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[tag]**: `[operator]` or `[live]`, as above; converge adds `[behaviour]` and `[pin]`.
- **[P]**: can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–USn, from spec.md.
- Name the exact files a task edits or reads, so the route's `Read first:` and lanes can
  be derived from the tasks.

---

## Phase 1: Setup (the baseline)

**Purpose**: confirm the tree's gates pass on this branch before anything changes, so any
later failure is this feature's own; read, writing nothing, what the host and Infrahub hold.

- [ ] T001 Run the pure gates and read the tree's state; report each in this task's note.

---

## Phase 2: Foundational

**Purpose**: what every later phase stands on (moved helpers, frozen contract copies, new
names), landed first so the tree keeps compiling.

- [ ] T00x …

**Checkpoint**: the tree is green and nothing user-visible has changed.

---

## Phase 3: User Story 1 - [Title] (Priority: P1) 🎯 MVP

**Goal**: one sentence.

**Independent Test**: how this story is proved on its own (the tier and the test names).

- [ ] T0xx [US1] …

**Checkpoint**: what holds once this phase is done.

---

[One phase per user story, in the plan's order; then the documents, the host (live), and
the records at the close.]

---

## Phase N: The records at the close

**Purpose**: `docs/verified-facts.md`, the roadmap's feature row and paragraph, `CLAUDE.md`'s
Formats and State, the closing gates and greps, then the operator's review `[operator]`.

- [ ] T0xx …

---

## Dependencies & Execution Order

### Phase dependencies

One line per phase: what it waits on, and which of its tasks run in parallel.

### Within a phase

Task order where it matters (`T008 → T009 → T010; T013 any time in the phase`).

### Parallel opportunities

The `[P]` tasks, and the runs below that may be laned.

---

## Implementation Strategy

**Incremental delivery**: the phases in order, each a green tree; name the MVP checkpoint.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

**Grouping rule.** A run is the tasks that share one context: one package with its tests,
or one document set. Its ids need not be contiguous. A run names at most eight files under
`Read first:`; a records run names at most four documents. Split a run that would exceed
either, since a run that reads five packages fills its context and a run of nine record
tasks exhausts its budget.

**Lane rule.** `[∥ Run M]` after `**Run N**` says Run N may run beside Run M, in its own
worktree, merged back in route order. Mark it only when the two runs edit disjoint files
and read disjoint `Read first:` sets, no edge in Dependencies joins them, neither names
tier 2, tier 3, a hand scenario or the host, and neither carries `[operator]` or `[live]`.
`analyze` checks each mark.

**Line grammar**, which `scripts/converge-loop.sh` parses:

```
N. **Run N** [∥ Run M] — <what the run builds> (T0xx–T0yy, T0zz). Read first: path/a.go, path/b_test.go. Only these; stop and report.
```

An `[operator]` or `[live]` run says so in place of "Only these": `**Run N** — [live] …
(T0xx). Stop and report.`

1. **Run 1** — the baseline: the pure gates and the tree's state read (T001). Read first: Makefile. Only this; stop and report.
2. **Run 2** — … (T0xx–T0yy). Read first: … Only these; stop and report.

`converge` follows the last run.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route"
only up to the next heading. What `analyze` must settle, and anything a run should know
that no task line carries, goes here.
