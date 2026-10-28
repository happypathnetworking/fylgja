---
name: "converge-loop"
description: "Run the feature chain attended: start scripts/converge-loop.sh --attended from the stage asked for (specify through converge), show the operator each session's report as it lands, carry each question to the operator and the answer back, and keep it going. `stop` ends a running loop."
argument-hint: "[stop] [--from STAGE] [--to STAGE] [--feature specs/NNN-slug] [--lanes N] [--plan-effort high|xhigh] [--implement-effort high|xhigh] [--max-passes N] [--budget-usd D] [--live-budget-usd D] [--no-converge] [--no-planned]"
compatibility: "Requires scripts/converge-loop.sh and an interactive session the operator replies to; never under claude -p"
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

You are the **attended session** of `docs/development.md`'s "The attended loop" (a bold
paragraph, not a heading: `grep -n '^\*\*The attended loop' docs/development.md`). Read it
first; it is the contract, and this file only says what to do in which order. The script owns
the tree from a session's start to its post-run checks. You write into the tree **only under
the pause handshake** while the loop runs, and you never run tier 3, a twin or the worker
yourself: the loop's live sessions do, with the node logins.

**Stay answerable.** The loop can raise a question at any moment, and its only channel to you
is a Monitor event, which reaches you only between turns. So you never block: you ask the
operator **in plain text and end your turn**, never with `AskUserQuestion` while the loop
runs; you wait in the background, never in a foreground loop. A question you leave without a
verdict for `--verdict-timeout` (900s) is taken as `hold`: the loop stalls until you land it.

**Show the work.** Every session the loop runs ends in a report, and the operator reads it
here, from you, as it lands: never make them wait for a Monitor's expiry or open a file.

`state.py` (beside this file) reads where everything stands from disk:
`python3 -I .claude/skills/converge-loop/state.py [--feature specs/NNN-slug]`. It names the
run directory (`RUN`, and `ATT=$RUN/attended`), whether the loop process lives, whether it is
running, paused or stopped, the last session of each run with its report, any lane worktree
kept, and for each question its verdict or reply and what it still needs.

## Stop

If the arguments start with `stop`: touch `$ATT/stop` for the run `state.py` names, and once
it reports `stopped` (within a minute) go to **Report**. Nothing else.

## Start

1. **Which stage.** `--from` names the first stage (default `implement`): `specify`, `clarify`,
   `plan`, `tasks`, `analyze`, `implement` or `converge`; `--to` the last (default
   `converge`). From `specify`, `--feature specs/NNN-slug` is required, since
   `.specify/feature.json` still names the previous feature; `/feature-open` hands over here.
2. **Preconditions.** Refuse, saying why, if any fails:
   - the tree is dirty (`git status --porcelain`);
   - from `specify`: the branch is `main`, `specs/NNN-slug/brief.md` exists, its "Open, for
     clarify" section reads `none`, its "Operator steps" has no open box, and no branch
     `NNN-slug` exists; from any later stage: the branch is the feature's, the last path
     element of `.specify/feature.json`'s `feature_directory` (or of `--feature`);
   - another loop holds `local/converge-loop.lock` (`flock -n local/converge-loop.lock true`);
   - `local/.env` lacks either node login, `INFRAHUB_ADDRESS` or `INFRAHUB_API_TOKEN`
     (`--attended` refuses too, but say it first; check the names, never print a value);
   - this session is not on the model `docs/development.md`'s table gives `/converge-loop`
     (ask the operator to `/model` it first).
3. **Carry the skips.** `python3 -I .claude/skills/converge-loop/state.py --carry` prints the
   tasks the feature's last run skipped that are still unchecked. Pass them as
   `--skip "<ids>"`, so a task the operator kept for themself is not run again.
4. **Start the script** detached, passing the arguments through:

   ```bash
   SKIP=$(python3 -I .claude/skills/converge-loop/state.py --carry)
   setsid nohup scripts/converge-loop.sh --attended ${SKIP:+--skip "$SKIP"} $ARGUMENTS > local/converge-loop.out 2>&1 < /dev/null &
   ```

   Within ten seconds `state.py` names the new run. If the script exits instead, report
   `local/converge-loop.out` and stop. `setsid` forks, so the pid you have is not the loop's:
   the files are what you watch.
5. **Tell the operator** in one line: the stages, the summary's path, the tasks carried as
   skipped, and that `/converge-loop stop` ends it.

## Watch

Arm one `Monitor` over the run's events file, every line an event, for the longest it allows
(`timeout_ms` 1800000), and re-arm it on every expiry:

```bash
tail -n 0 -F $RUN/events.jsonl
```

Each line is JSON with a `kind`:

- `session`: a session ended; go to **Relay**;
- `stage`, `gates`, `merge`, `pass`: one line to the operator each (below);
- `question`: a question; go to **Answer**;
- `paused`, `resumed`: the handshake's bookkeeping; say nothing;
- `stopped`: go to **Report**.

**On every wake, reconcile first.** Whatever woke you (a Monitor event, its expiry or kill, a
notice that tasks did not finish before the previous session ended, a background task, the
operator's message), run `state.py` before anything else, and act on what it lists, not on the
event alone: a question with `NO VERDICT` or `NO REPLY` gets its verdict or its question to
the operator now; a session report not yet shown is shown; `stopped` goes to **Report**;
`PAUSED` goes to **Land**. Then re-arm the Monitor if it expired, was killed or did not
survive a restart. When no Monitor is running, none is watching, so re-arm whenever unsure.

Monitor events are not the operator's replies; never treat one as an answer.

## Relay a session's report

On a `session` event, read the file its `report` names, the headless session's final message,
and show it to the operator **verbatim**, under one line naming the stage or run (`label`),
the model and effort, the exit status and the tasks (`tasks`); cut it at about 4 KB and name
the path when it is longer. Then one line for what follows it, as the events arrive: the
stage's gate (`stage`: passed, or the loop stopped), the gates (`gates`: pass, or the log's
path), a lane's merge (`merge`: merged at a commit, or the conflict's log), a convergence
pass (`pass`: the tasks appended with their tags, or nothing). Say nothing more: the report
is the session's own account, and the operator reads it as written.

## Answer a question

A question carries `id`, `kind`, `run`, `tasks`, `report` and `sentence`. Its kind decides
the path:

- **`unchecked`** (an implement session left these tasks) and **`operator-tagged`** (a
  convergence pass appended `[operator]` tasks): the verdict path below.
- **`clarify`** and **`analyze`** (a chain stage would have asked the operator): the text path
  below. There is no verdict and no handshake, since the stage's session is still open and
  nothing but it writes the tree.

### The verdict path

Do the first two **within a minute**.

1. **Read the report** at `report` and the tasks' lines in `tasks.md`. Find what each task
   needs: a decision, a changed artifact, a host, or something else.
2. **Write the verdict** to `$ATT/verdict-<id>`, one word:
   - `continue` when no unchecked task of the next planned run names the blocked tasks'
     identifiers, files or types in its text and tasks.md's Dependencies section does not
     name their phase, so the loop may go on while the operator decides;
   - `hold` otherwise, and when unsure;
   - `stop` only when the operator has already said so.
3. **A standing answer.** When a note under each task already records the operator's answer
   from an earlier question, and the report adds nothing that note did not weigh, land that
   answer (**Land**) and tell the operator in one line which answer you reused. Do not ask
   again.
4. **Ask the operator in plain text, then end your turn.** One numbered question per blocked
   decision; tasks that share a decision share a question. For each: the tasks, what the
   report says they need, and lettered options: the report's own, the one it recommends
   first, then `skip these tasks` and `stop the loop`. End with the reply's form, for example
   "Reply `1a 2skip`". Several questions open at once are asked together.
5. **When the operator replies**, go to **Land**. A `stop the loop` reply: touch `$ATT/stop`
   and go to **Report**.

### The text path

1. **Read the report** at `report`: its `## Questions` (clarify) or `## For the operator`
   (analyze), each with options and the session's recommendation.
2. **Put them to the operator in plain text, then end your turn**: the questions as the report
   asks them, numbered, with the recommendation first among each one's options, then
   `take your recommendations` and `stop the loop`. End with the reply's form.
3. **When the operator replies**, write the reply **verbatim** to `$ATT/reply-<id>`, one file,
   nothing added: the script hands it to the session that asked, which records it where the
   command records an answer, and the stage's commit carries it. A `take your recommendations`
   reply: touch `$ATT/skip-<id>` instead. A `stop the loop` reply: touch `$ATT/stop` and go to
   **Report**. No pause and no commit: you touched nothing in the tree.

## Land an answer

1. **Draft before you pause.** Work out the edit the answer needs, where the repository's own
   rules put it (`docs/development.md`):
   - a decision: a new entry in `docs/decisions.md` that supersedes the old one, then
     `docs/architecture.md` grepped for the old position; a constitution amendment cites it;
   - a changed requirement: a `spec.md` or `plan.md` edit;
   - a choice a task left open, and any work the answer calls for: a dated note under that
     task in `tasks.md`, with the operator's answer; the loop builds an answered task, and a
     new task is converge's to append, never yours;
   - a task the operator did by hand: ticked.

   When the edit needs wording the operator did not give (a decision entry, an amendment, a
   requirement's new text), show them the draft, the exact lines, and end your turn; land it
   on their OK. A value they did not give (a figure, a threshold, a name) is asked for, never
   chosen. A note quoting their answer, or a tick, needs no OK.
2. **If the loop has stopped** (`state.py` says `stopped` or `DEAD`), there is no handshake:
   write, commit, and go to **Report**'s restart.
3. **Otherwise pause.** Touch `$ATT/pause` and wait for `$ATT/paused` in the background
   (`run_in_background`, `until [ -e $ATT/paused ]; do sleep 5; done`), never in the
   foreground: it can take up to an hour, the running session's gates and command log first.
4. Apply the edits, then commit by hand: a conventional commit whose body says why, with the
   trailer the session reminder gives. Never commit `local/`.
5. For each question settled, touch `$ATT/answer-<id>`; for a `skip these tasks` reply, add the
   note under each task saying it is left for the operator and why, commit, and touch
   `$ATT/skip-<id>` instead.
6. Touch `$ATT/resume`. The script checks the tree (clean, on the branch, no token) and plans
   again; the summary says `resumed at <sha>; answered: ...`.

Several answers ready together land under one pause.

## Report

When the loop stops, read the summary's tail and `state.py`, and tell the operator: the outcome
and its sentence; the commits (`git log --oneline <start>..HEAD` from the summary's last
line); every question still open or skipped and what each needs; and, for `gate`, `contract`,
`golden` or `merge`, what to look at before starting again: for `merge`, the lane's worktree
under `local/lanes/` and its branch `lane/<run>`, which the operator merges by hand
(`git merge lane/<run>`), commits, and removes (`git worktree remove`, `git branch -d`). Put
any open question to them as in **Answer**.

**Restart.** After `operator`, `cap` or a stop that left questions open, once their answers
have landed, offer to start the loop again, from the stage the stop left (`--from`); on the
operator's yes, go to **Start** (its preconditions and carried skips included). After `gate`,
`contract`, `golden` or `merge`, offer it only once the operator says the tree has been
reviewed. After `done`, `converged` or `rule`, what follows is the operator's: the next stage,
or the feature's close.

## Never

- Write into the tree while the loop runs and is not paused, or run `make test-contract`,
  `make test-e2e`, a twin or the worker: the live sessions do that, with the logins.
- Block: `AskUserQuestion` while the loop runs, or a foreground wait.
- Treat a Monitor event as the operator's reply, or a question's absence as consent.
- Paraphrase a session's report, or an operator's reply on its way to `reply-<id>`.
- Push, or print, log or commit the Infrahub token or either node login.
