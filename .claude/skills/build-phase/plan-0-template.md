# Phase N: branches, worktrees, the order of the plans, and the names they share

Phase N is <count> plans (`design/core.md`, "Phase N"; D-0xx to D-0yy), each a branch and a
pull request useful on its own, merged into one integration branch.

- **The integration branch** is `phase-N-integration`, cut from `main` with the design branch
  merged in first: `git checkout -b phase-N-integration main && git merge --no-ff phase-N-design`.
- **Each plan's branch** is `phase-N/<n>-<name>`, cut from `phase-N-integration` at the time it
  starts, in a worktree at `../fylgja-core-wt/<n>-<name>` (`git worktree add <path> -b <branch>
  phase-N-integration` from the main checkout), with `make venv` run there before the baseline
  `make test`.
- **Order**: <which plans are independent and may run in parallel worktrees; which follows
  which; which closes>. A plan merges into `phase-N-integration` (`--no-ff`) when its final
  review passes, and the next plan's branch is cut after that merge.
- **One live run at a time**: <which plans have live or cluster tests, and what must never
  run together>.
- **Every commit** passes `make lint` and `make test`; `make linkcheck` where Markdown changes.
  Conventional commits whose body says why. Never push unless asked. Never commit `local/`.

| Plan | Branch | File |
|---|---|---|
| 1 <title> | `phase-N/1-<name>` | `YYYY-MM-DD-phaseN-1-<name>.md` |

## The names the plans share

Each plan's implementer sees its own plan alone. These are the names and signatures a later
plan relies on from an earlier one; a plan that must bend one says so in its Global
Constraints, and the plan that consumes it is corrected before it starts.

### Where the design's plan list is bent

- <what lands in another plan than the design says, and why>

### Test tiers and markers

- <the marker, directory and make target of each tier the phase adds>

### Plan 1

- <module, name, signature, and what consumes it>

## Reconciled after the plans were drafted

- <each point settled where two plans met, and which plans carry it>
