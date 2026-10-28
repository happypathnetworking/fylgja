# quickstart.md

The section list `plan` writes `specs/NNN-slug/quickstart.md` to: how the feature is
exercised by hand and by the tiers, in the order the route runs them. Each section names
the success criteria and user stories it proves.

## 0. Before the work: the operator's

The steps the brief's Operator steps ticked, repeated as checks (not as work), and
anything the host must hold before Run 1.

## 1. Tier 1

The commands, and what must not move (goldens, fixture ids).

## 2. By hand: <the first scenario>

Commands and expected output, one scenario per section, numbered on: the hand tools, the
command under test, the refusals, the documents a reader checks.

## N-2. Tier 2

The command, the tests named, how long it takes, and what Infrahub must be left holding.

## N-1. Tier 3

The command, which cases prove the feature, the expected `E2E-OK` line and time, and the
host's state before and after.

## N. The records at the close

The documents the close updates, the greps, and the figures to record (times, the
estimate against the measured effort).
