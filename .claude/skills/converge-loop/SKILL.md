---
name: "converge-loop"
description: "Run the feature's converge loop attended: start scripts/converge-loop.sh --attended, carry each question it raises to the operator, land the answer between sessions, and keep it going. `stop` ends a running loop."
argument-hint: "[stop] [--max-passes N] [--budget-usd D] [--live-budget-usd D] [--no-converge] [--no-planned]"
compatibility: "Requires scripts/converge-loop.sh and an interactive session (AskUserQuestion); never under claude -p"
metadata:
  author: "fylgja"
  source: "docs/development.md, The attended loop"
user-invocable: true
disable-model-invocation: true
---

## User Input

```text
$ARGUMENTS
```

You are the **attended session** of `docs/development.md`'s "The attended loop". Read that
section first; it is the contract, and this file only says what to do in which order. The
script owns the tree from a session's start to its post-run checks. You write into the tree
**only under the pause handshake**, and you never run tier 3, a twin or the worker yourself:
the loop's live sessions do, with the node logins, and you watch.

## Stop

If the arguments start with `stop`: find the running loop's directory (the newest under
`local/converge-loop/` whose `attended/` exists and whose `summary.md` has no `## Stopped`
line), touch `attended/stop`, and report the summary's last lines once `## Stopped` appears
(within a minute; the script checks the flag between every wait). Nothing else.

## Start

1. **Preconditions.** Refuse, saying why, if any fails: the tree is dirty (`git status
   --porcelain`); another loop holds `local/converge-loop.lock` (`flock -n`); `local/.env` is
   missing either node login (`--attended` refuses too, but say it first); this is not an
   interactive session (you cannot `AskUserQuestion`).
2. **Start the script** detached, passing the arguments through:

   ```bash
   setsid nohup scripts/converge-loop.sh --attended $ARGUMENTS > local/converge-loop.out 2>&1 < /dev/null &
   ```

   Within ten seconds `local/converge-loop.out` has a `Started ...; this file is
   local/converge-loop/<started>/summary.md` line; `RUN=local/converge-loop/<started>` and
   `ATT=$RUN/attended`. If it exits instead (a dirty tree, the lock, a missing login), report
   its message and stop. Do not `wait` on the pid: `setsid` forks, so the pid you have is
   not the loop's; the files are what you watch.
3. **Tell the operator** in one line where the summary and the questions file are, and that
   they can `/converge-loop stop` at any time.

## Watch

Arm one `Monitor` over the summary and the questions file together, and **re-arm it every
time it expires** (it expires every 30 minutes; a run lasts hours):

```bash
tail -n 0 -F $RUN/summary.md $ATT/questions.jsonl 2>/dev/null | grep --line-buffered -E '^\{|^- question|^  verdict|^- paused|^  resumed|^## Stopped|^- implement|^  build|^  session'
```

Every event is a line of either file. Act on three kinds and relay the rest in a sentence
when the operator asks:

- a JSON line (`questions.jsonl`): a **question**; go to **Answer**;
- `- paused ...`: the script is between sessions and waiting for you; go to **Land**;
- `## Stopped: <outcome>`: go to **Report**.

Monitor events are not the operator's replies. Never treat one as an answer.

## Answer a question

A question line carries `id`, `kind` (`unchecked`: an implement session left these tasks;
`operator-tagged`: a convergence pass appended `[operator]` tasks), `run`, `tasks`,
`report` and `sentence`. Do this in order, and do the first two **within a minute**: the
script waits `--verdict-timeout` (900s) for a verdict and then stops as unattended.

1. **Read the report** at `report` (the session's reply) and the tasks' lines in the
   feature's `tasks.md`. Find what each task needs: a decision, a changed artifact, a host,
   or something else.
2. **Write the verdict** to `$ATT/verdict-<id>`, one word:
   - `continue` when no unchecked task of the next planned run names the blocked tasks'
     identifiers, files or types in its text and tasks.md's Dependencies section does not
     name their phase, so the loop may go on while you ask;
   - `hold` otherwise, and when unsure;
   - `stop` only when the operator has already said so.
   The script logs `verdict <id>: <word>` in the summary.
3. **Ask the operator** with `AskUserQuestion`: the question's `sentence`, what the report
   says the tasks need, the options the report itself gives, plus `skip these tasks` and
   `stop the loop`. One question per blocked decision; several tasks that share one
   decision share one question.
4. **When the operator answers**, go to **Land**. A `stop the loop` answer: touch
   `$ATT/stop` and go to **Report**.

## Land an answer

Nothing is written to the tree until the script says it is paused.

1. Touch `$ATT/pause`. Wait for `$ATT/paused` (the script writes it at its next
   between-sessions point: after the running session's gates and command log, which may be
   up to an hour). Wait with a Bash `until [ -e ... ]; do sleep 5; done` in the background,
   not by polling in the foreground.
2. Apply the answer **where it belongs**, by the repository's own rules
   (`docs/development.md`): a decision is a new entry in `docs/decisions.md` that supersedes
   the old one, then `docs/architecture.md` is grepped for the old position; a changed
   requirement is a `spec.md` or `plan.md` edit; a choice a task left open is a note under
   that task in `tasks.md`, dated, with the operator's answer; a task the operator did by
   hand is ticked. Commit by hand, a conventional commit whose body says why, with the
   trailer the session reminder gives. Never commit `local/`.
3. For each question settled, touch `$ATT/answer-<id>`. For a `skip these tasks` answer,
   add the note under each task saying it is left for the operator and why, commit, and
   touch `$ATT/skip-<id>` instead: the tasks stay excluded and the loop goes on without them.
4. Touch `$ATT/resume`. The script checks the tree (clean, on the branch, no token) and
   plans again; the summary says `resumed at <sha>; answered: ...`.

Several answers that arrive together land under one pause.

## Report

When `## Stopped: <outcome>` appears, read the summary's tail and tell the operator: the
outcome and its sentence; the commits (`git log --oneline <start>..HEAD` from the
summary's last line); any question still open or skipped and what each needs; and, for
`gate`, `contract` or `golden`, what to look at before starting again. Stop watching.

## Never

- Write into the tree while the script is not paused, or run `make test-contract`,
  `make test-e2e`, a twin or the worker: the live sessions do that, with the logins.
- Treat a Monitor event as the operator's reply, or a question's absence as consent.
- Push, or print, log or commit the Infrahub token or either node login.
