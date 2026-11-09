# House rules for every implementer and reviewer of a phase

The controller hands this file to each subagent with its task. Read `AGENTS.md` and
`CONTRIBUTING.md` in your worktree first; they bind every change.

- **Where you work.** Only in the worktree your dispatch names. Never edit, stage or commit
  anything in the main checkout or in another worktree. Never push. Never commit `local/`.
  Never touch `local/plans/`: the controller ticks a plan's boxes.
- **Gates.** Every commit passes `make lint` and `make test`, run from the worktree's root,
  and `make linkcheck` where Markdown changed. Read a gate's status directly, never through a
  pipe: `if make lint > /tmp/lint.log 2>&1; then echo ok; else tail -20 /tmp/lint.log; fi`.
- **Tests first means run first.** Run each new test and see it fail before the code that
  makes it pass exists, and keep that output for your report.
- **Never run a formatter.** The tree is wrapped by hand, and a reflow of lines your task did
  not change is out of scope. `make lint` (ruff's checks and mypy) is the gate.
- **Never run the tests as a shell background job** (`&`): such a child ignores SIGINT, and
  one server test sends it.
- **Commits.** Conventional commits whose body says why; where your brief gives the message,
  use it. End each with the trailer line your dispatch gives.
- **The tree holds no host name, address or value of a site.** Tests and fixtures use the
  documentation ranges (192.0.2.0/24, 198.51.100.0/24) and reserved names (`*.example`).
- **Credentials are never printed, logged or written.** `local/.env` exists in the main
  checkout alone: load it in the same command as the run that needs it
  (`set -a; . <main checkout>/local/.env; set +a; …`) and never show it.
- **Live, Docker and cluster runs** happen only when your dispatch says the window is yours,
  one at a time, and you remove whatever you started.
- **A behaviour of a running system** is read before a line relies on it, and recorded in
  `design/verified-facts.md` with the version and the date, in that document's style.
- **A fact says what a run showed, and no more.** A figure worked out from other figures is
  called a derivation. Whether a reading calls for a bound, a wider wait or nothing is not
  yours to write into a fact: put it in your report's concerns, and the controller rules.
- **Formats change in `formats/`**, in the same commit as the code. `design/decisions.md` is
  append-only: never rewrite an entry.
- **Prose** in documents and docstrings follows the text around it: plain and specific.
- **When the brief and the code disagree**, and neither the brief nor the plan's constraints
  says which is right, stop and report `NEEDS_CONTEXT` with the file and the line. Never
  rewrite a decision or widen the task to make it fit.
- **You dispatch no subagent**, and no reviewer of your own work: the controller sends one.
- **The shell.** `cd` persists between calls: use absolute paths or a subshell. Where
  `grep` on this machine skips git-ignored files, use `/usr/bin/grep` for anything under
  `local/`. Never run `pkill -f` or `pgrep -f` with a pattern your own command line matches.
