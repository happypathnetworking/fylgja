---
name: "feature-open"
description: "Open a feature: check the previous one closed and the host clean, settle every open point of specs/NNN-slug/brief.md with the operator and move it into Decided, draft any decision entry, tick or list the operator's steps, commit the brief, and hand over to /converge-loop --from specify."
argument-hint: "specs/NNN-slug [--check-only]"
compatibility: "Requires an interactive session the operator replies to, and the brief at specs/NNN-slug/brief.md written to docs/templates/brief-template.md; never under claude -p"
metadata:
  author: "fylgja"
  source: "docs/development.md, The feature chain"
user-invocable: true
disable-model-invocation: true
---

## User Input

```text
$ARGUMENTS
```

You open the feature whose directory the first argument names, so that the chain
(`/converge-loop --from specify`) starts with nothing left to ask: everything the operator can
settle before `specify` is settled here, in conversation, and lands in the brief. You write
nothing the brief's template (`docs/templates/brief-template.md`) has no section for, and you
never run a Spec Kit command yourself.

## 1. Check

Run `python3 -I .claude/skills/feature-open/check.py <specs/NNN-slug>` and show the operator
its table. It prints one line per check and exits 1 when any fails:

- the previous feature closed: every task of the feature `.specify/feature.json` names is
  `[X]`, the tree is clean, nothing is pending in the command log
  (`python3 .claude/hooks/command-log.py flush` publishes it; run it, then re-check), no
  twin (`clab inspect --all` is `{}`, no `local/twin`), and the worker and the server run a
  binary that is not `(deleted)`;
- Spec Kit installed, at the version `.specify/init-options.json` names, with every
  git-ignored file the chain needs present;
- `local/.env` names every variable (names alone, never a value);
- the brief exists, names the constitution's current version, its "Open, for clarify"
  section reads `none`, and its "Operator steps" has no open box;
- `origin` is fetched (`git fetch origin`, a read), so `specify`'s hook moves nothing later;
- the branch `NNN-slug` does not exist.

With `--check-only`, stop after the table. A failed check that is yours to fix (the command
log pending, `origin` unfetched) you fix and re-run; one that is the operator's (a twin up, a
task of the previous feature open) you report and stop.

## 2. Settle the brief

Read the brief whole, then the previous feature's `spec.md` Hand-off, if any, and work
through these with the operator, **one question at a time, in plain text**, ending your turn
after each:

1. **Each item under "Open, for clarify"**: put it with its options and your recommendation
   first; on the answer, move it into **Decided** as one sentence with its reason, dated and
   attributed to the operator, and strike it from Open. When the last is moved, Open reads
   `none`.
2. **Each decision that supersedes an entry of `docs/decisions.md`**: draft the entry from
   `docs/templates/decision-template.md`, show the exact lines, and append it on the
   operator's OK, with the superseded entry's *Superseded* status line. A number is the next
   free `D-NNN`.
3. **Each box under "Operator steps"**: ask whether it is done now; a done step is ticked, a
   step that must wait for the chain (a push, an import of what the chain writes) is listed
   with its command and becomes the route's `[operator]` task, with its reason.
4. **The staleness check** the brief's own first paragraph asks for: the constitution version
   it names against `.specify/memory/constitution.md`'s, and each "Where the shape is fixed"
   bullet against the decision it cites; a mismatch is a question to the operator, never a
   silent edit.

## 3. Commit and hand over

Commit the brief (and `docs/decisions.md` when an entry was appended) by hand, a conventional
commit whose body says why, with the trailer the session reminder gives. Run `check.py` once
more; when it passes, tell the operator the chain is ready and that
`/converge-loop --from specify --feature specs/NNN-slug` starts it, with `--plan-effort high`
for a port, the default `xhigh` for new design.

## Never

- Run a `/speckit-*` command, boot a twin, or touch the worker or the server.
- Decide an open item yourself: each is the operator's, and your recommendation is one option.
- Write outside the brief and `docs/decisions.md`.
- Print, log or commit the Infrahub token or either node login.
