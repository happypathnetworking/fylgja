# research.md

The section list `plan` writes `specs/NNN-slug/research.md` to, and `implement` appends
to. Headings exactly as below; one line each on what belongs there.

## 1. Verified at plan

One subsection per fact checked against the running system (Infrahub, containerlab, a
node, Temporal, the host) before the plan relied on it: the command or query, the answer,
the version and the date. Each later lands in `docs/verified-facts.md` once it holds.

## 2. Decisions

`R-01`, `R-02`, …: each design decision the plan takes, with the alternatives and the
reason, and the spec requirement it serves. A decision the operator must take is marked so
and drafted under §3.

## 3. Drafted for the operator

The decision entry (from `docs/templates/decision-template.md`) and any constitution
amendment, as they will be appended, for the operator's OK at `analyze`. "None" when
nothing is drafted.

## 4. Owed at implement

What implement must verify or record before relying on it: a fact §1 could not check, a
figure to measure (tier times, an estimate), a document to bring to the code.

## 5. Verified at implement

Appended by the runs: each item of §4 with its result, version and date, and anything a
run found that the plan did not foresee.
