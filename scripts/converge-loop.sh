#!/bin/bash
# The feature's implement runs, then the converge→implement cycle, unattended
# (docs/development.md, "Spec Kit workflow"). Each command runs as its own headless
# `claude -p` session, so every one starts from a fresh context on the model and effort its
# table row names, reads its inputs from disk, and is logged by the command-log hook like a
# typed command. Everything it finishes is committed on the current branch; nothing is pushed.
#
# Stage 1, the planned runs. tasks.md's "Recommended route" lists them, one line each:
# `N. **Run N** — <what> (T0xx–T0yy, T0zz)`. The line is the run's prompt, as it was when
# typed, and the parenthesised IDs are its tasks. Without a route, each `## Phase` is a run.
# A run whose tasks are all [X] is skipped, so a stopped loop resumes where it stopped. After
# the route, each phase's unchecked tasks the route does not name are a run of their own (a
# phase added after the route was written, a convergence task left open). The plan is read
# again before every session, so a run left part-ticked is listed again with what is left.
#
# Stage 2, convergence. One pass: /speckit-converge, which tags each task it appends
# [behaviour], [pin] or [operator] (and, attended, [live]); the script commits the phase;
# then /speckit-implement of exactly those tasks. Attended, before each pass and before a
# "cap" stop, every asked task that was answered and is still unchecked is implemented (an
# answer that landed while a session ran, after its pass had implemented the rest), so an
# answer is never left unbuilt.
#
# After every implement session: the session has committed its own work; the pure gates run
# (make build, bin/fylgja static, make test, make lint); the command log is published and
# committed (command-log.py flush --commit). Entries kept before the loop are committed first.
#
# The loop stops, and hands back to the operator, at the first of:
#
#   converged    a converge pass appended nothing (the stopping rule's second clause)
#   rule         two consecutive passes appended only [pin] tasks, and the second is
#                implemented and gated (the stopping rule's first clause)
#   operator     a run the operator owns: its line or a task is tagged [operator], or it
#                names tier 3, the hand scenarios or a quiet host (or tier 2, when the
#                sessions have no Infrahub credentials); or implement left a task unchecked.
#                Attended (below), these are questions instead, and the loop stops here only
#                on a "stop" verdict, a question nobody answered, or a stop flag
#   golden       a run moved testdata/golden/; review that commit, then run the loop again
#   contract     a session wrote where it may not: converge outside tasks.md or above its
#                phase, implement ticking another run's task, left uncommitted changes, moved
#                off the branch, or pushed; or a commit would carry the Infrahub token
#   gate         a gate failed after implement; never retried, never handed back to a model
#   cap          --max-passes convergence passes ran
#   error        a claude session exited non-zero (including --max-budget-usd reached)
#
# Unattended, it never pushes, boots a twin, runs tier 3, or touches the worker. Its sessions
# get Infrahub's address and token from local/.env, so an implement session runs the tier-2
# tests its tasks name (the Infrahub it reaches is a development
# instance). They never get the node logins, so a task that needs a twin stays unchecked
# and stops the loop. Without the two Infrahub variables the loop runs as before, and tier 2
# is the operator's too.
#
# Attended (--attended; docs/development.md, "The attended loop"), an interactive session
# started the loop (the /converge-loop skill) and is watching. Three things change, and
# nothing else: (1) a run that needs live infrastructure runs as a *live session*, a headless
# session that does get both node logins and the live clause (the worker, twins, tier 3 and
# the hand scenarios are its, by CLAUDE.md's rules), with its own budget; (2) what would end
# the loop at "operator" is a *question* instead: a line appended to
# local/converge-loop/<started>/attended/questions.jsonl, after which the script waits for
# the attended session's verdict file, `continue` (go on with the next run, the question's
# tasks excluded until answered), `hold` (wait for the answer) or `stop`; (3) the attended
# session writes answers into the tree only under the pause handshake: it writes `pause`,
# the script answers `paused` once it is between sessions, the attended session edits,
# commits, writes `answer-<n>` for each question it settled and `resume`, and the script
# checks the tree and plans again. A `stop` flag ends the loop at the next check. A verdict
# that does not arrive within --verdict-timeout ends the loop at "operator", as unattended.
#
# No commit may carry the token's value: every commit a session makes, and every commit
# the script makes, is searched for it first, and the loop stops at "contract" on a match.
# Nothing is pushed, so such a commit can still be rewritten.
#
# Every run and pass leaves a tree snapshot (a git tree object, untracked files included, no
# ref or index touched), so `git diff <before> <after>` shows its work alone. The summary,
# each session's report and the gate logs are in local/converge-loop/<started>/.
#
# Usage: scripts/converge-loop.sh [--max-passes N] [--budget-usd D] [--no-planned]
#                                 [--no-converge] [--allow-dirty]
#                                 [--attended [--live-budget-usd D] [--verdict-timeout S]]
#   --max-passes       convergence passes before stopping at "cap" (default 7)
#   --budget-usd       ceiling per claude session, passed as --max-budget-usd (default 25)
#   --no-planned       skip stage 1
#   --no-converge      stop after stage 1 ("planned", exit 0)
#   --allow-dirty      start on a tree with uncommitted changes; they stay uncommitted, and
#                      the uncommitted-changes check is off
#   --attended         an interactive session is watching (above)
#   --live-budget-usd  ceiling for a live session (default twice --budget-usd)
#   --verdict-timeout  seconds to wait for a verdict before stopping at "operator" (default 900)
#
# Exit 0 for converged, rule and planned; 2 for operator, golden, contract and cap; 1 for
# gate and error.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

MAX_PASSES=7
BUDGET_USD=25
LIVE_BUDGET_USD=""
VERDICT_TIMEOUT=900
ALLOW_DIRTY=0
PLANNED=1
CONVERGE=1
ATTENDED=0
while [ $# -gt 0 ]; do
	case "$1" in
	--max-passes) MAX_PASSES="$2"; shift 2 ;;
	--budget-usd) BUDGET_USD="$2"; shift 2 ;;
	--live-budget-usd) LIVE_BUDGET_USD="$2"; shift 2 ;;
	--verdict-timeout) VERDICT_TIMEOUT="$2"; shift 2 ;;
	--no-planned) PLANNED=0; shift ;;
	--no-converge) CONVERGE=0; shift ;;
	--allow-dirty) ALLOW_DIRTY=1; shift ;;
	--attended) ATTENDED=1; shift ;;
	*) echo "converge-loop: unknown argument $1" >&2; exit 2 ;;
	esac
done
[ -n "$LIVE_BUDGET_USD" ] || LIVE_BUDGET_USD=$((BUDGET_USD * 2))

# The table rows (docs/development.md): converge and implement on Opus 5.5 at xhigh.
CONVERGE_MODEL=claude-opus-5-5
IMPLEMENT_MODEL=claude-opus-5-5
EFFORT=xhigh

# golangci-lint lives in $GOPATH/bin, which a non-login shell may not have.
PATH="$PATH:$(go env GOPATH)/bin"

# Infrahub's address and token, for tier 2. The same file carries the node logins, which
# run_claude strips from every session but a live one: unattended, twins stay the operator's.
if [ -f local/.env ]; then
	set -a
	# shellcheck disable=SC1091
	. local/.env
	set +a
fi
TIER2=0
if [ -n "${INFRAHUB_ADDRESS:-}" ] && [ -n "${INFRAHUB_API_TOKEN:-}" ]; then TIER2=1; fi
LOGINS=0
if [ -n "${FYLGJA_SRLINUX_USERNAME:-}" ] && [ -n "${FYLGJA_SRLINUX_PASSWORD:-}" ] &&
	[ -n "${FYLGJA_EOS_USERNAME:-}" ] && [ -n "${FYLGJA_EOS_PASSWORD:-}" ]; then LOGINS=1; fi

# What each session is told about live infrastructure, by whether it has tier 2.
if [ "$TIER2" = 1 ]; then
	IMPLEMENT_LIVE="Do not boot a twin, run make test-e2e, or start or stop the worker. Tier 2 is yours: INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN are in your environment, so run the tier-2 tests your tasks name (go test -count=1 -tags contract -run '<test>' ./<package>, or make test-contract where a task asks for the whole tier), leave no throwaway branch or fylgja-test-* series behind, and never print, log or commit the token. A task that needs a twin, tier 3 or the worker"
	CONVERGE_LIVE="or live infrastructure beyond tier 2 (tier 3, a twin, the worker); a tier-2 test is [pin] or [behaviour] like any other"
else
	IMPLEMENT_LIVE="Do not boot a twin, run make test-contract or make test-e2e, or start or stop the worker. A task that needs one of those"
	CONVERGE_LIVE="or live infrastructure (tier 2, tier 3, a twin, the worker)"
fi
# What a live session is told instead: the host is its, by CLAUDE.md's rules.
IMPLEMENT_LIVE_OK="This is a live run, and the host is yours by CLAUDE.md's rules: INFRAHUB_ADDRESS, INFRAHUB_API_TOKEN and both node logins are in your environment. Rebuild and restart the worker from this tree before any live run (CLAUDE.md's detached command, then verify it as CLAUDE.md says), start the dev server if it is down, read free -m before tier 3, run make test-e2e and the hand scenarios your tasks name, and leave the host clean when you stop: clab inspect --all is {}, no local/twin, no Schedule, no fylgja-test-* branch or series. You run headless: a reply that ends your turn ends the session and kills what you started, so never end your turn, or wait for a background task's notification, while a command you started still runs. make test-e2e outlasts one Bash call (about 17 minutes against the call's 10), so remove local/converge-e2e.out, start the tier detached with its exit status in that file, setsid nohup bash -c 'make test-e2e > local/converge-e2e.out 2>&1; echo exit \$? >> local/converge-e2e.out' < /dev/null > /dev/null 2>&1 &, then wait in foreground calls of under ten minutes, timeout 540 bash -c 'until grep -q ^exit local/converge-e2e.out; do sleep 10; done', repeated until it has exited, and read its result from that file; do the same for any other command that outlasts a call. Never print, log or commit the token or either login. A task the host refuses after a second attempt"
# Attended, converge separates what needs a decision from what needs the host.
if [ "$ATTENDED" = 1 ]; then
	CONVERGE_TAGS="[behaviour] when its fix changes what the code does; [pin] when it is a test, a doc or record line, or a named constant, with the code under test unchanged (the stopping rule in docs/development.md); [live] when it needs live infrastructure beyond tier 2 (tier 3, a twin, the worker, a hand scenario) and no decision; [operator] when it needs what only the operator can give: a choice between designs the artifacts do not settle, a change to spec.md, plan.md or docs/decisions.md, a golden or fixture id that would move. A tier-2 test is [pin] or [behaviour] like any other. Example: '- [ ] T<next id> [pin] Pin ...'"
else
	CONVERGE_TAGS="[behaviour] when its fix changes what the code does; [pin] when it is a test, a doc or record line, or a named constant, with the code under test unchanged (the stopping rule in docs/development.md); [operator] when it needs what only the operator can give: a choice between designs the artifacts do not settle, a change to spec.md, plan.md or docs/decisions.md, a golden or fixture id that would move, $CONVERGE_LIVE. Example: '- [ ] T<next id> [pin] Pin ...'"
fi

FEATURE_DIR=$(bash .specify/scripts/bash/check-prerequisites.sh --paths-only | sed -n 's/^FEATURE_DIR: //p')
TASKS="$FEATURE_DIR/tasks.md"
[ -f "$TASKS" ] || { echo "converge-loop: no tasks.md at $TASKS" >&2; exit 2; }
FEATURE_REL=${FEATURE_DIR#"$PWD"/}
SCOPE=$(basename "$FEATURE_DIR" | cut -d- -f1) # NNN-slug → NNN, the commit scope
BRANCH=$(git symbolic-ref --short HEAD)

if [ "$ATTENDED" = 1 ] && [ "$LOGINS" = 0 ]; then
	echo "converge-loop: --attended needs both node logins in local/.env for its live sessions" >&2
	exit 2
fi

# Entries the hook kept for sessions before the loop (an operator's typed commands) are
# published and committed first, so they neither dirty the tree nor ride in a session's commit.
pre_status=0
CLAUDE_PROJECT_DIR="$PWD" python3 .claude/hooks/command-log.py flush --commit --what "the sessions before the loop" || pre_status=$?
if [ "$pre_status" != 0 ]; then
	echo "converge-loop: publishing the pending command log failed (exit $pre_status; 3 means it carries the Infrahub token)" >&2
	exit 2
fi

if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$(git status --porcelain)" ]; then
	echo "converge-loop: the tree has uncommitted changes; commit them, or pass --allow-dirty" >&2
	exit 2
fi

mkdir -p local
exec 9> local/converge-loop.lock
flock -n 9 || { echo "converge-loop: another loop holds local/converge-loop.lock" >&2; exit 2; }

RUN_DIR="local/converge-loop/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN_DIR"
SUMMARY="$RUN_DIR/summary.md"
TRAILER="Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
ATT="$RUN_DIR/attended"
QUESTIONS="$ATT/questions.jsonl"
[ "$ATTENDED" = 0 ] || { mkdir -p "$ATT"; : > "$QUESTIONS"; }

say() { printf '%s\n' "$*" | tee -a "$SUMMARY"; }

# A tree object of the working tree as it stands, untracked files included and ignored
# files excluded, built in a throwaway index so neither the real index nor any ref moves.
snapshot() {
	local idx
	idx=$(mktemp)
	GIT_INDEX_FILE="$idx" git read-tree HEAD
	GIT_INDEX_FILE="$idx" git add -A
	GIT_INDEX_FILE="$idx" git write-tree
	rm -f "$idx"
}

remote_refs() { git for-each-ref --format='%(refname) %(objectname)' refs/remotes; }
REMOTE_REFS=$(remote_refs)

checked_ids() { grep -oE '^\s*- \[[xX]\] T[0-9]+' "$TASKS" | grep -oE 'T[0-9]+' || true; }

# Run one command as a headless session and then log it. The hook's own Stop fires before
# a headless session's reply reaches the transcript and so records nothing (verified on
# Claude Code 2.1.280); calling its stop mode once the session has exited reads the whole
# transcript through the same code path, task deltas included. A live session (4th argument
# "live") keeps both node logins and gets the live budget; every other session has neither.
# A session started from inside an interactive one is not a nested one (verified
# 2026-10-02: a `claude -p` from a session's shell, its CLAUDE_* variables inherited, ran
# and wrote its transcript as any session does), so nothing is unset for that.
run_claude() { # <model> <out file> <prompt> [live]
	local model="$1" out="$2" prompt="$3" live="${4:-}" sid transcript status=0
	local -a strip=(-u FYLGJA_SRLINUX_USERNAME -u FYLGJA_SRLINUX_PASSWORD -u FYLGJA_EOS_USERNAME -u FYLGJA_EOS_PASSWORD)
	local budget="$BUDGET_USD"
	if [ "$live" = live ]; then strip=(); budget="$LIVE_BUDGET_USD"; fi
	sid=$(python3 -c 'import uuid; print(uuid.uuid4())')
	SESSION_HEAD=$(git rev-parse HEAD)
	env "${strip[@]}" \
		claude -p --session-id "$sid" --model "$model" --effort "$EFFORT" \
		--permission-mode auto --max-budget-usd "$budget" "$prompt" \
		< /dev/null > "$out" 2>&1 || status=$?
	transcript=$(ls "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1 || true)
	if [ -n "$transcript" ]; then
		printf '{"session_id":"%s","transcript_path":"%s"}' "$sid" "$transcript" |
			CLAUDE_PROJECT_DIR="$PWD" python3 .claude/hooks/command-log.py stop > /dev/null || true
	fi
	say "  session $sid, $model${live:+ ($live, budget \$$budget)}, exit $status, report $out"
	return "$status"
}

# Whether stdin carries the token's value. grep reads all of its input (no -q, whose early
# exit would fail the pipe under pipefail), and reads the value from a file descriptor, so
# it never appears in a process's arguments.
carries_token() {
	if [ -z "${INFRAHUB_API_TOKEN:-}" ]; then
		cat > /dev/null
		return 1
	fi
	grep -F -f <(printf '%s\n' "$INFRAHUB_API_TOKEN") > /dev/null
}

# Publish and commit what the command-log hook kept for a session (command-log.py flush), and
# nothing else: each commands/ directory it touched, as its own commit. flush refuses, exit 3,
# a directory whose diff carries the token.
commit_log() { # <what the session was>
	local out status=0
	out=$(CLAUDE_PROJECT_DIR="$PWD" python3 .claude/hooks/command-log.py flush --commit --what "$1" \
		--body "Written by the command-log hook, whose stop mode scripts/converge-loop.sh runs once each headless session has exited: the hook's own Stop fires before the reply reaches the transcript.") || status=$?
	[ -z "$out" ] || say "  $out (command log)"
	[ "$status" != 3 ] || finish contract 2 "The command log for $1 carries the value of INFRAHUB_API_TOKEN, so it was not committed. Remove it from the commands/ directory before anything else."
	[ "$status" = 0 ] || finish error 1 "Publishing the command log for $1 failed (exit $status)."
}

# The checks every session must pass, whatever it was asked to do.
check_session() {
	[ "$(git symbolic-ref --short HEAD 2>/dev/null)" = "$BRANCH" ] ||
		finish contract 2 "The session left branch $BRANCH."
	[ "$(remote_refs)" = "$REMOTE_REFS" ] ||
		finish contract 2 "A remote-tracking ref moved: the session pushed or fetched."
	if git log -p "$SESSION_HEAD..HEAD" | carries_token; then
		finish contract 2 "A commit since $(git rev-parse --short "$SESSION_HEAD") carries the value of INFRAHUB_API_TOKEN. Nothing was pushed: rewrite those commits before anything else."
	fi
}

finish() { # <outcome> <exit status> <sentence>
	local end open=""
	end=$(snapshot)
	say ""
	say "## Stopped: $1"
	say ""
	say "$3"
	[ -z "$(echo ${OPEN:-})" ] || open=" Still open, excluded from every plan and pass: $(echo $OPEN)."
	[ -z "$(echo ${SKIPPED:-})" ] || open="$open Skipped, left for the operator: $(echo $SKIPPED)."
	[ -z "$(echo ${ASKED:-})" ] || [ -z "$(echo $(answered_unchecked))" ] ||
		open="$open Answered and not yet implemented: $(echo $(answered_unchecked))."
	[ -z "$open" ] || say "${open# }"
	say ""
	say "The loop's whole diff: git diff $START_TREE $end"
	say "Its commits: git log --oneline $START_HEAD..HEAD ($(git rev-list --count "$START_HEAD"..HEAD) commits, none pushed)."
	exit "$2"
}

# --- The attended protocol -------------------------------------------------------------
#
# OPEN holds the task ids of every question with a `continue` or `hold` verdict and no answer
# yet, and SKIPPED those the attended session answered "skip" (left unchecked, with a note,
# for the operator); the planner leaves both out. ASKED holds every task id put to a
# question, so the asked tasks answered and still unchecked can be implemented before the
# next pass. QN numbers the questions from 1.
OPEN=""
SKIPPED=""
ASKED=""
QN=0

json_str() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

stop_requested() { [ "$ATTENDED" = 1 ] && [ -e "$ATT/stop" ]; }

# Put a question to the attended session and act on its verdict. Unattended, this is the
# "operator" stop it replaces. Returns on `continue` (the ids are now excluded) and after a
# `hold` has been answered; exits on `stop`, on a stop flag, or when no verdict arrives.
ask() { # <kind> <label> <ids> <report or -> <sentence>
	local kind="$1" label="$2" ids="$3" report="$4" sentence="$5" verdict="" waited=0
	[ "$ATTENDED" = 1 ] || finish operator 2 "$sentence"
	QN=$((QN + 1))
	ASKED="$ASKED $ids"
	printf '{"id":%d,"kind":%s,"run":%s,"tasks":%s,"report":%s,"sentence":%s,"asked_at":%s}\n' \
		"$QN" "$(json_str "$kind")" "$(json_str "$label")" "$(json_str "$(echo $ids)")" \
		"$(json_str "$report")" "$(json_str "$sentence")" "$(json_str "$(date -u +%FT%TZ)")" >> "$QUESTIONS"
	say "- question $QN ($kind): $label, tasks $(echo $ids), report $report"
	say "  $sentence"
	while [ ! -s "$ATT/verdict-$QN" ]; do
		stop_requested && finish operator 2 "The attended session asked the loop to stop while question $QN waited for a verdict."
		if [ "$waited" -ge "$VERDICT_TIMEOUT" ]; then
			finish operator 2 "Question $QN had no verdict after ${VERDICT_TIMEOUT}s: $sentence"
		fi
		sleep 2
		waited=$((waited + 2))
	done
	verdict=$(tr -d '[:space:]' < "$ATT/verdict-$QN")
	say "  verdict $QN: $verdict"
	case "$verdict" in
	continue) OPEN="$OPEN $ids" ;;
	hold)
		OPEN="$OPEN $ids"
		say "  holding for an answer to question $QN"
		while [ ! -e "$ATT/answered-$QN" ] && [ ! -e "$ATT/skipped-$QN" ]; do
			stop_requested && finish operator 2 "The attended session asked the loop to stop while question $QN was held."
			wait_for_pause
			pause_point
		done
		;;
	stop) finish operator 2 "The attended session answered stop to question $QN: $sentence" ;;
	*) finish contract 2 "Question $QN's verdict is '$verdict', not continue, hold or stop." ;;
	esac
}

# Block until the attended session asks to pause (or to stop). Used when the loop has
# nothing it may do until an answer lands.
wait_for_pause() {
	while [ ! -e "$ATT/pause" ]; do
		stop_requested && finish operator 2 "The attended session asked the loop to stop."
		sleep 5
	done
}

# Between sessions: if the attended session asked to pause, let it write, then check what it
# wrote and lift the exclusion of every question it answered. Unattended, a no-op.
pause_point() {
	[ "$ATTENDED" = 1 ] || return 0
	stop_requested && finish operator 2 "The attended session asked the loop to stop."
	[ -e "$ATT/pause" ] || return 0
	local head answered="" id ids
	head=$(git rev-parse HEAD)
	: > "$ATT/paused"
	say "- paused for the attended session at $(git rev-parse --short "$head")"
	while [ ! -e "$ATT/resume" ]; do
		stop_requested && finish operator 2 "The attended session asked the loop to stop while paused."
		sleep 2
	done
	rm -f "$ATT/pause" "$ATT/paused" "$ATT/resume"
	SESSION_HEAD="$head"
	check_session
	if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$(git status --porcelain)" ]; then
		finish contract 2 "The attended session resumed the loop with uncommitted changes: $(git status --porcelain | tr '\n' ' ')"
	fi
	local skipped=""
	for f in "$ATT"/answer-* "$ATT"/skip-*; do
		[ -e "$f" ] || continue
		id=${f##*-}
		ids=$(python3 -c 'import json,sys
for l in open(sys.argv[1]):
    q=json.loads(l)
    if str(q["id"])==sys.argv[2]: print(q["tasks"])' "$QUESTIONS" "$id")
		OPEN=$(tr ' ' '\n' <<< "$OPEN" | grep -vxF -f <(tr ' ' '\n' <<< "$ids") | tr '\n' ' ' || true)
		case "$f" in
		*/answer-*) answered="$answered $id"; mv "$f" "$ATT/answered-$id" ;;
		*/skip-*) skipped="$skipped $id"; SKIPPED="$SKIPPED $ids"; mv "$f" "$ATT/skipped-$id" ;;
		esac
	done
	say "  resumed at $(git rev-parse --short HEAD)${answered:+; answered:$answered}${skipped:+; skipped:$skipped}"
}

# The asked tasks whose question has been answered (neither open nor skipped) and that are
# still unchecked, in the order they were asked.
answered_unchecked() {
	local id
	for id in $(tr ' ' '\n' <<< "$ASKED" | awk 'NF && !seen[$0]++'); do
		grep -qwF "$id" <<< "$OPEN $SKIPPED" && continue
		grep -qE "^\s*- \[[xX]\] $id\b" "$TASKS" && continue
		echo "$id"
	done | tr '\n' ' '
}

# Implement exactly <ids>, then check, gate and log it. Returns only when all is well, or
# when a question about what was left has a `continue` or an answered `hold`.
implement() { # <label> <ids> <prompt> <report file> [live]
	local label="$1" ids="$2" line="$3" out="$4" live="${5:-}" before_checked before_tree after_tree stray gate_log open moved clause
	before_checked=$(checked_ids)
	before_tree=$(snapshot)
	clause="$IMPLEMENT_LIVE"
	[ "$live" != live ] || clause="$IMPLEMENT_LIVE_OK"
	say "- implement $label${live:+ ($live)}: $(echo $ids)"
	run_claude "$IMPLEMENT_MODEL" "$out" "/speckit-implement $line
Loop run (scripts/converge-loop.sh). Only $(echo $ids | sed 's/ /, /g'); stop at the run's checkpoint and report, and do not start another run. $clause, or a decision you cannot take from spec.md, plan.md, research.md or docs/decisions.md, stays unchecked and your report says what it needs. End with make build, make test and make lint. Then commit your work, the ticks in tasks.md included, on the current branch as conventional commits whose bodies say why, split as this repository splits them (a golden re-baseline in a commit of its own). Never push." ${live:+"$live"} ||
		{ commit_log "$label"; finish error 1 "The implement session failed; its report is $out."; }
	commit_log "$label"
	check_session

	stray=$(comm -13 <(echo "$before_checked" | sort) <(checked_ids | sort) | grep -vxF -f <(echo "$ids" | tr ' ' '\n') || true)
	[ -z "$stray" ] || finish contract 2 "Implement of $label ticked tasks outside it: $(echo $stray)."

	say "- gates"
	gate_log="${out%.md}.gates.log"
	{ make build && [[ $(file bin/fylgja) == *'statically linked'* ]] && make test && make lint; } > "$gate_log" 2>&1 ||
		finish gate 1 "A gate failed after $label; see $gate_log."
	say "  build, static, test, lint: pass"

	if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$(git status --porcelain)" ]; then
		finish contract 2 "Implement of $label left uncommitted changes: $(git status --porcelain | tr '\n' ' ')"
	fi
	after_tree=$(snapshot)
	say "  diff: git diff $before_tree $after_tree"

	# Captured before matching: under pipefail, grep -q's early exit would fail the pipe.
	moved=$(git diff --name-only "$before_tree" "$after_tree")
	if grep -q '^testdata/golden/' <<< "$moved"; then
		finish golden 2 "$label moved testdata/golden/. Review its commit, then run the loop again to go on."
	fi

	open=""
	for id in $ids; do
		grep -qE "^\s*- \[[xX]\] $id\b" "$TASKS" || open="$open $id"
	done
	[ -z "$open" ] || ask unchecked "$label" "$open" "$out" "Implement of $label left$open unchecked; its report ($out) says why."
}

# The planned runs, as TSV: label, 1 if it needs the host (live), its unchecked IDs, its
# line. Only runs with an unchecked task not under an open or skipped question are listed;
# with <ids>, only those tasks, and an [operator] tag no longer makes a run live, since the
# question that tag raised has been answered.
planned_runs() { # [<ids>]
	python3 - "$TASKS" "$TIER2" "$OPEN $SKIPPED" "${1:-}" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
tasks = {m.group(2): (m.group(1) != " ", m.group(3))
         for m in re.finditer(r"^\s*- \[([ xX])\] (T\d+)\b(.*)$", text, re.M)}
excluded = set(sys.argv[3].split())
only = set(sys.argv[4].split())
LIVE = r"\[operator\]|\[live\]|tier 3|hand scenario|quiet host|test-e2e"
if sys.argv[2] != "1":  # the sessions have no Infrahub credentials: tier 2 is the operator's
    LIVE += r"|tier 2|test-contract"
LIVE = re.compile(LIVE, re.I)

def expand(s):
    out = []
    for a, b in re.findall(r"(T\d+)(?:\s*[–-]\s*(T\d+))?", s):
        if b:
            out += [f"T{i:0{len(a) - 1}d}" for i in range(int(a[1:]), int(b[1:]) + 1)]
        else:
            out.append(a)
    return out

phases = []
for m in re.finditer(r"^## (Phase \d+)[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S):
    title = m.group(0).splitlines()[0][3:]
    phases.append((m.group(1), title, re.findall(r"^\s*- \[[ xX]\] (T\d+)\b", m.group(2), re.M)))

# The route's runs, then each phase's tasks the route does not name (a phase added after
# the route was written, a convergence phase). Without a route, each phase is a run.
runs = []
route = re.search(r"^### Recommended route[^\n]*\n(.*?)(?=^#)", text, re.M | re.S)
if route:
    for line in route.group(1).splitlines():
        r = re.match(r"\s*\d+\.\s+\*\*(Run \d+)\*\*\s*[—-]\s*(.*)", line)
        if r:
            ids = [i for g in re.findall(r"\(([^)]*T\d+[^)]*)\)", r.group(2)) for i in expand(g)]
            runs.append((r.group(1), f"{r.group(1)} — {r.group(2).strip()}", ids))
covered = {i for _, _, ids in runs for i in ids}
for label, title, ids in phases:
    rest = [i for i in ids if i not in covered]
    if rest:
        runs.append((label, title, rest))
        covered.update(rest)

for label, line, ids in runs:
    todo = list(dict.fromkeys(i for i in ids if i in tasks and not tasks[i][0] and i not in excluded
                              and (not only or i in only)))
    if not todo:
        continue
    tag = r"\s*\[live\]" if only else r"\s*\[(operator|live)\]"
    live = LIVE.search(line) or any(re.match(tag, tasks[i][1]) for i in todo)
    print(f"{label}\t{1 if live else 0}\t{' '.join(todo)}\t{line}")
EOF
}

new_task_ids() { # <tasks.md before> <tasks.md after>: IDs of the appended tasks
	tail -c +"$(($(stat -c%s "$1") + 1))" "$2" | grep -oE '^\s*- \[[ xX]\] T[0-9]+' | grep -oE 'T[0-9]+' || true
}

tag_of() { # <task id> <tasks.md>: the tag converge put after the ID, or nothing
	grep -oE "^\s*- \[[ xX]\] $1 \[(behaviour|pin|live|operator)\]" "$2" | grep -oE '(behaviour|pin|live|operator)' || true
}

START_TREE=$(snapshot)
START_HEAD=$(git rev-parse HEAD)
say "# Converge loop, $FEATURE_REL"
say ""
say "Started $(date -u +%FT%TZ) on $BRANCH at $(git rev-parse --short HEAD), tree $START_TREE; this file is $SUMMARY."
say "Converge $CONVERGE_MODEL, implement $IMPLEMENT_MODEL, effort $EFFORT, at most $MAX_PASSES passes, \$$BUDGET_USD per session."
if [ "$TIER2" = 1 ] && [ "$ATTENDED" = 1 ]; then
	say "Tier 2: the sessions have Infrahub's address and token (local/.env); the node logins go to live sessions alone."
elif [ "$TIER2" = 1 ]; then
	say "Tier 2: the sessions have Infrahub's address and token (local/.env); never the node logins."
else
	say "Tier 2: the sessions have no Infrahub credentials, so tier 2 is the operator's."
fi
if [ "$ATTENDED" = 1 ]; then
	say "Attended: questions in $QUESTIONS, verdicts and flags in $ATT/, live sessions at \$$LIVE_BUDGET_USD, verdicts within ${VERDICT_TIMEOUT}s."
fi

# Implement the planned runs one at a time, reading the plan again before each. With <ids>,
# only those tasks, and an open question is not waited on: the loop goes on to its pass.
# Returns 0 when it implemented something, 1 when there was nothing to run.
run_planned() { # [<ids>]
	local only="${1:-}" run label live ids line slug none=1
	while :; do
		pause_point
		run=$(planned_runs "$only" | head -1)
		if [ -z "$run" ]; then
			if [ -z "$only" ] && [ -n "$(echo $OPEN)" ]; then
				say "- nothing to run until a question is answered (open: $(echo $OPEN)${SKIPPED:+; skipped: $(echo $SKIPPED)})"
				wait_for_pause
				continue
			fi
			break
		fi
		none=0
		IFS=$'\t' read -r label live ids line <<< "$run"
		say ""
		say "### $line"
		slug=$(echo "$label" | tr 'A-Z ' 'a-z-')
		if [ "$live" = 1 ]; then
			if [ "$ATTENDED" = 1 ]; then
				implement "$label" "$ids" "$line" "$RUN_DIR/$slug.implement.md" live
			else
				finish operator 2 "$label is the operator's (live infrastructure, or tagged [operator]): ${line%.}. Do it by hand, tick its tasks, commit, and run the loop again."
			fi
		else
			implement "$label" "$ids" "$line" "$RUN_DIR/$slug.implement.md"
		fi
	done
	return "$none"
}

if [ "$PLANNED" = 1 ]; then
	say ""
	say "## Planned runs"
	run_planned || say "Every planned task is checked."
fi

[ "$CONVERGE" = 1 ] || finish planned 0 "Every planned run is implemented; convergence was not asked for."

# Land a pending answer, then build every asked task answered after its pass's implement
# began, so no answer is left unbuilt; a pin streak does not count across what it changes.
carry_answered() { # <heading>
	local carried
	pause_point
	carried=$(answered_unchecked)
	[ -n "$(echo $carried)" ] || return 0
	say ""
	say "## Answered $1: $(echo $carried)"
	run_planned "$carried" || true
	PIN_STREAK=0
}

PIN_STREAK=0
for pass in $(seq 1 "$MAX_PASSES"); do
	carry_answered "before pass $pass"
	say ""
	say "## Convergence pass $pass"
	before_tasks="$RUN_DIR/pass-$pass.tasks-before.md"
	cp "$TASKS" "$before_tasks"
	before_tree=$(snapshot)

	say "- converge"
	run_claude "$CONVERGE_MODEL" "$RUN_DIR/pass-$pass.converge.md" "/speckit-converge Loop pass $pass (scripts/converge-loop.sh). Tag every task you append directly after its ID with exactly one of: $CONVERGE_TAGS. The append contract is otherwise unchanged; do not commit." ||
		{ commit_log "convergence pass $pass"; finish error 1 "The converge session failed; its report is $RUN_DIR/pass-$pass.converge.md."; }
	check_session

	after_tree=$(snapshot)
	stray=$(git diff --name-only "$before_tree" "$after_tree" |
		grep -vxF "$FEATURE_REL/tasks.md" | grep -vE "^$FEATURE_REL/commands/" || true)
	[ -z "$stray" ] || finish contract 2 "Converge wrote outside tasks.md: $(echo "$stray" | tr '\n' ' ')"
	cmp -s -n "$(stat -c%s "$before_tasks")" "$before_tasks" "$TASKS" ||
		finish contract 2 "Converge changed tasks.md above its new phase: diff $before_tasks $TASKS"

	if cmp -s "$before_tasks" "$TASKS"; then
		commit_log "convergence pass $pass"
		finish converged 0 "Pass $pass appended nothing."
	fi

	ids=$(new_task_ids "$before_tasks" "$TASKS")
	[ -n "$ids" ] || finish contract 2 "Pass $pass appended to tasks.md but no task line."
	all_pin=1
	operator=""
	live_ids=""
	plain_ids=""
	tags=""
	for id in $ids; do
		tag=$(tag_of "$id" "$TASKS")
		case "$tag" in
		pin) plain_ids="$plain_ids $id" ;;
		operator) operator="$operator $id"; all_pin=0 ;;
		live) live_ids="$live_ids $id"; all_pin=0 ;;
		behaviour) plain_ids="$plain_ids $id"; all_pin=0 ;;
		*) all_pin=0; plain_ids="$plain_ids $id"; say "  $id carries no tag; counted as [behaviour]" ;;
		esac
		tags="$tags"$'\n'"- $id [${tag:-untagged}]"
		say "  $id [${tag:-untagged}]"
	done
	first=$(echo "$ids" | head -1)
	last=$(echo "$ids" | tail -1)
	span=$first
	[ "$first" = "$last" ] || span="$first–$last"
	if git diff HEAD -- "$TASKS" | carries_token; then
		finish contract 2 "Pass $pass's phase carries the value of INFRAHUB_API_TOKEN, so it was not committed. Remove it from $TASKS before anything else."
	fi
	git commit -q -m "docs($SCOPE): convergence pass $pass appends $span" \
		-m "Found by /speckit-converge, run unattended by scripts/converge-loop.sh against the tree at $(git rev-parse --short HEAD). The phase names each gap with its evidence; the tags decide the stopping rule and whether the loop may implement them:$tags" \
		-m "$TRAILER" -- "$TASKS"
	say "  committed $(git rev-parse --short HEAD) (the phase)"
	commit_log "convergence pass $pass"

	asked=0
	if [ -n "$operator" ]; then
		# Unattended this ends the loop before anything is implemented. Attended it is a
		# question; on `continue` the rest of the pass is implemented around it, and an
		# answered task still unchecked (and not skipped) is implemented with the rest.
		ask operator-tagged "pass $pass" "$operator" "$RUN_DIR/pass-$pass.converge.md" "Pass $pass appended tasks that need the operator:$operator. Nothing was implemented."
		asked=1
		for id in $operator; do
			grep -qE "^\s*- \[[xX]\] $id\b" "$TASKS" && continue
			grep -qwF "$id" <<< "$OPEN $SKIPPED" && continue
			plain_ids="$plain_ids $id"
		done
	fi
	[ -z "$(echo $plain_ids)" ] || implement "pass $pass" "$(echo $plain_ids)" "Convergence pass $pass's tasks." "$RUN_DIR/pass-$pass.implement.md"
	[ -z "$(echo $live_ids)" ] || implement "pass $pass" "$(echo $live_ids)" "Convergence pass $pass's live tasks." "$RUN_DIR/pass-$pass.live.md" live

	if [ "$all_pin" = 1 ] && [ "$asked" = 0 ]; then PIN_STREAK=$((PIN_STREAK + 1)); else PIN_STREAK=0; fi
	[ "$PIN_STREAK" -lt 2 ] || finish rule 0 "Passes $((pass - 1)) and $pass changed no behaviour; both are implemented and gated."
done

carry_answered "after the last pass"
finish cap 2 "$MAX_PASSES passes ran and the last still appended work."
