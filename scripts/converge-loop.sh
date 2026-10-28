#!/bin/bash
# The feature chain: specify → clarify → plan → tasks → analyze → the implement runs → the
# converge→implement cycle (docs/development.md, "Spec Kit workflow"). Each command runs as
# its own headless `claude -p` session, so every one starts from a fresh context on the
# model and effort its table row names, reads its inputs from disk, and is logged by the
# command-log hook like a typed command. Everything it finishes is committed on the current
# branch; nothing is pushed. --from and --to choose the stages; by default the loop starts
# at the implement runs, as it always did.
#
# Stage 0, the chain's first five commands, each gated on the tree before the next starts:
# specify (its prompt is the brief's fenced line; the git extension's hook creates the
# feature's branch inside the session, the one remote fetch the loop allows) gates on
# spec.md with no [NEEDS CLARIFICATION] and a checklist with no open box; clarify runs by
# --resume in specify's session and ends its report with CLARIFY-DONE, or CLARIFY-WAIT above
# the questions it would have asked, which attended become one text question to the
# operator and unattended stop the loop; plan gates on plan.md's Constitution Check filled
# and research.md's sections; tasks gates on a route the planner reads whole, every line
# with its Read first, every [operator] task with its reason; analyze applies what the
# artifacts settle, ends ANALYZE-DONE or ANALYZE-WAIT like clarify, and the tasks gate runs
# again. The script commits each stage's artifacts, the feature directory alone.
#
# Stage 1, the planned runs. tasks.md's "Recommended route" lists them, one line each:
# `N. **Run N** [∥ Run M] — <what> (T0xx–T0yy, T0zz). Read first: …`. The line is the run's
# prompt, as it was when typed, and the parenthesised IDs are its tasks, contiguous or not.
# Without a route, each `## Phase` is a run. A run whose tasks are all [X] is skipped, so a
# stopped loop resumes where it stopped. After the route, each phase's unchecked tasks the
# route does not name are a run of their own (a phase added after the route was written, a
# convergence task left open). The plan is read again before every session
# (scripts/converge-plan.py), so a run left part-ticked is listed again with what is left.
#
# Lanes. Two runs that mark each other `[∥ Run M]` run at once, each as a headless session
# in its own worktree under local/lanes/ on a branch lane/<run>, seeded with the git-ignored
# files Spec Kit needs (symlinks to this tree's). Each lane commits on its branch; the script
# merges the lanes back in route order (tasks.md by scripts/merge-tasks.py, which resolves
# ticks and notes alone), then runs the checks and gates once on the merged tree. A merge
# that needs a judgement stops the loop at "merge" with the worktrees kept. Only pure runs
# are laned: never a live one, nor one that names tier 2, which shares one Infrahub.
#
# Stage 2, convergence. One pass: /speckit-converge, which tags each task it appends
# [behaviour], [pin] or [operator] (and, attended, [live]); the script commits the phase;
# then /speckit-implement of exactly those tasks. Attended, before each pass and before a
# "cap" stop, every asked task that was answered and is still unchecked is implemented (an
# answer that landed while a session ran, after its pass had implemented the rest), so an
# answer is never left unbuilt.
#
# After every implement session: the session has committed its own work; the pure gates run
# (make build, bin/fylgja static, make test, make lint); the command log is published
# (command-log.py flush --commit, which commits nothing here: the log's directories are
# git-ignored). Entries kept before the loop are published first. Every session's end, every
# gate, merge, pass and stop is also one JSON line in local/converge-loop/<started>/events.jsonl,
# which the attended session watches.
#
# The loop stops, and hands back to the operator, at the first of:
#
#   done         the stages --to asked for ran, before the implement runs
#   converged    a converge pass appended nothing (the stopping rule's second clause)
#   rule         two consecutive passes appended only [pin] tasks, and the second is
#                implemented and gated (the stopping rule's first clause)
#   operator     a run the operator owns: its line or a task is tagged [operator], or it
#                names tier 3, the hand scenarios or a quiet host (or tier 2, when the
#                sessions have no Infrahub credentials); or implement left a task unchecked.
#                Attended (below), these are questions instead, and the loop stops here only
#                on a "stop" verdict or a stop flag
#   golden       a run moved testdata/golden/; review that commit, then run the loop again
#   contract     a session wrote where it may not: converge outside tasks.md or above its
#                phase, implement ticking another run's task, left uncommitted changes, moved
#                off the branch, or pushed; or a commit would carry the Infrahub token
#   merge        a lane's branch does not merge back mechanically; its worktree and branch
#                are kept under local/lanes/ for the operator to merge by hand
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
# that does not arrive within --verdict-timeout is taken as `hold`: nothing runs, so nothing
# is spent, until the attended session (restarted, if it died) lands an answer or a stop.
# --skip starts the loop with tasks already skipped, as a `skip-<n>` would leave them: the
# skill passes the tasks a previous run of the feature skipped and that are still unchecked.
#
# No commit may carry the token's value: every commit a session makes, and every commit
# the script makes, is searched for it first, and the loop stops at "contract" on a match.
# Nothing is pushed, so such a commit can still be rewritten.
#
# Every run and pass leaves a tree snapshot (a git tree object, untracked files included, no
# ref or index touched), so `git diff <before> <after>` shows its work alone. The summary,
# each session's report and the gate logs are in local/converge-loop/<started>/.
#
# Usage: scripts/converge-loop.sh [--from STAGE] [--to STAGE] [--feature specs/NNN-slug]
#                                 [--plan-effort high|xhigh] [--implement-effort high|xhigh]
#                                 [--max-passes N] [--budget-usd D] [--no-planned]
#                                 [--no-converge] [--allow-dirty] [--lanes N] [--dry-run]
#                                 [--attended [--live-budget-usd D] [--verdict-timeout S]
#                                             [--skip IDS]]
#   --from, --to       the first and last stage to run, of specify, clarify, plan, tasks,
#                      analyze, implement, converge (default implement to converge)
#   --feature          the feature's directory; required for --from specify, when
#                      .specify/feature.json still names the previous feature
#   --plan-effort      plan's effort: xhigh for new design (default), high for a port
#   --implement-effort the planned implement runs' effort (default high); live and
#                      converge-appended runs are xhigh whatever this says
#   --max-passes       convergence passes before stopping at "cap" (default 7)
#   --budget-usd       ceiling per claude session, passed as --max-budget-usd (default 25)
#   --no-planned       skip the implement runs (--from converge)
#   --no-converge      stop after the implement runs ("planned", exit 0; --to implement)
#   --allow-dirty      start on a tree with uncommitted changes; they stay uncommitted, and
#                      the uncommitted-changes check is off
#   --lanes            runs that may run at once (default 2; 1 runs every run in this tree)
#   --dry-run          no claude session: each run is a stub that ticks its tasks, writes
#                      one file per task and commits, so the loop's mechanics can be
#                      exercised on a throwaway spec (docs/development.md)
#   --attended         an interactive session is watching (above)
#   --live-budget-usd  ceiling for a live session (default twice --budget-usd)
#   --verdict-timeout  seconds to wait for a verdict before taking it as hold (default 900)
#   --skip             task IDs (T056 or "T056 T074", unchecked) skipped from the start
#
# Exit 0 for done, converged, rule and planned; 2 for operator, golden, contract, merge and
# cap; 1 for gate and error.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

STAGES=(specify clarify plan tasks analyze implement converge)
stage_index() { # <stage>: its place in STAGES, or 99
	local i
	for i in "${!STAGES[@]}"; do [ "${STAGES[$i]}" != "$1" ] || { echo "$i"; return; }; done
	echo 99
}

MAX_PASSES=7
BUDGET_USD=25
LIVE_BUDGET_USD=""
VERDICT_TIMEOUT=900
ALLOW_DIRTY=0
ATTENDED=0
SKIP_ARG=""
LANES=2
DRY_RUN=0
FROM=implement
TO=converge
FEATURE_ARG=""
PLAN_EFFORT=xhigh
IMPLEMENT_EFFORT=high
while [ $# -gt 0 ]; do
	case "$1" in
	--from) FROM="$2"; shift 2 ;;
	--to) TO="$2"; shift 2 ;;
	--feature) FEATURE_ARG="${2%/}"; shift 2 ;;
	--plan-effort) PLAN_EFFORT="$2"; shift 2 ;;
	--implement-effort) IMPLEMENT_EFFORT="$2"; shift 2 ;;
	--max-passes) MAX_PASSES="$2"; shift 2 ;;
	--budget-usd) BUDGET_USD="$2"; shift 2 ;;
	--live-budget-usd) LIVE_BUDGET_USD="$2"; shift 2 ;;
	--verdict-timeout) VERDICT_TIMEOUT="$2"; shift 2 ;;
	--no-planned) FROM=converge; shift ;;
	--no-converge) TO=implement; shift ;;
	--allow-dirty) ALLOW_DIRTY=1; shift ;;
	--lanes) LANES="$2"; shift 2 ;;
	--dry-run) DRY_RUN=1; shift ;;
	--attended) ATTENDED=1; shift ;;
	--skip) SKIP_ARG="$SKIP_ARG ${2//,/ }"; shift 2 ;;
	*) echo "converge-loop: unknown argument $1" >&2; exit 2 ;;
	esac
done
[ -n "$LIVE_BUDGET_USD" ] || LIVE_BUDGET_USD=$((BUDGET_USD * 2))
[[ $LANES =~ ^[1-9][0-9]*$ ]] || { echo "converge-loop: --lanes takes a count, not '$LANES'" >&2; exit 2; }
for e in "$PLAN_EFFORT" "$IMPLEMENT_EFFORT"; do
	[[ $e == high || $e == xhigh ]] || { echo "converge-loop: an effort is high or xhigh, not '$e'" >&2; exit 2; }
done
FROM_I=$(stage_index "$FROM")
TO_I=$(stage_index "$TO")
[ "$FROM_I" != 99 ] && [ "$TO_I" != 99 ] || { echo "converge-loop: a stage is one of ${STAGES[*]}" >&2; exit 2; }
[ "$FROM_I" -le "$TO_I" ] || { echo "converge-loop: --from $FROM is after --to $TO" >&2; exit 2; }
IMPLEMENT_I=$(stage_index implement)
runs_stage() { [ "$FROM_I" -le "$(stage_index "$1")" ] && [ "$(stage_index "$1")" -le "$TO_I" ]; }

# The table rows (docs/development.md, "Model and effort per command"), set here and
# nowhere else. A planned implement run is `implement`; a live one `implement-live`; a
# run of what a convergence pass appended `implement-appended`.
declare -A MODEL=(
	[specify]=claude-fable-5-1 [clarify]=claude-fable-5-1 [plan]=claude-fable-5-1
	[tasks]=claude-fable-5-1 [analyze]=claude-fable-5-1 [converge]=claude-fable-5-1
	[implement]=claude-opus-5-5 [implement-live]=claude-opus-5-5 [implement-appended]=claude-opus-5-5
)
declare -A EFFORT=(
	[specify]=high [clarify]=high [plan]="$PLAN_EFFORT" [tasks]=high [analyze]=high [converge]=high
	[implement]="$IMPLEMENT_EFFORT" [implement-live]=xhigh [implement-appended]=xhigh
)
trailer_for() { # <model>: the commit trailer a commit made by or for that model carries
	case "$1" in
	claude-fable-*) echo "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" ;;
	*) echo "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" ;;
	esac
}

# What a session was asked for, read by run_claude's event line and the dry-run stub; and
# the session to resume instead of starting one (clarify in specify's; an answer in the
# session that asked), cleared by run_claude once used.
RUN_LABEL=""
RUN_IDS=""
RESUME_SID=""
LAST_SID=""

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
# Attended, converge separates what needs a decision from what needs the host. Attended
# requires tier 2 (below), so these tags take it as the sessions'.
if [ "$ATTENDED" = 1 ]; then
	CONVERGE_TAGS="[behaviour] when its fix changes what the code does; [pin] when it is a test, a doc or record line, or a named constant, with the code under test unchanged (the stopping rule in docs/development.md); [live] when it needs live infrastructure beyond tier 2 (tier 3, a twin, the worker, a hand scenario) and no decision; [operator] when it needs what only the operator can give: a choice between designs the artifacts do not settle, a change to spec.md, plan.md or docs/decisions.md, a golden or fixture id that would move. A tier-2 test is [pin] or [behaviour] like any other. Example: '- [ ] T<next id> [pin] Pin ...'"
else
	CONVERGE_TAGS="[behaviour] when its fix changes what the code does; [pin] when it is a test, a doc or record line, or a named constant, with the code under test unchanged (the stopping rule in docs/development.md); [operator] when it needs what only the operator can give: a choice between designs the artifacts do not settle, a change to spec.md, plan.md or docs/decisions.md, a golden or fixture id that would move, $CONVERGE_LIVE. Example: '- [ ] T<next id> [pin] Pin ...'"
fi

if [ -n "$FEATURE_ARG" ]; then
	FEATURE_DIR="$PWD/$FEATURE_ARG"
	[ -d "$FEATURE_DIR" ] || { echo "converge-loop: no directory $FEATURE_ARG" >&2; exit 2; }
else
	[ "$FROM" != specify ] || { echo "converge-loop: --from specify needs --feature specs/NNN-slug" >&2; exit 2; }
	FEATURE_DIR=$(bash .specify/scripts/bash/check-prerequisites.sh --paths-only | sed -n 's/^FEATURE_DIR: //p')
fi
TASKS="$FEATURE_DIR/tasks.md"
if [ "$FROM_I" -ge "$IMPLEMENT_I" ] && [ ! -f "$TASKS" ]; then
	echo "converge-loop: no tasks.md at $TASKS" >&2
	exit 2
fi
FEATURE_REL=${FEATURE_DIR#"$PWD"/}
FEATURE_NAME=$(basename "$FEATURE_DIR")       # NNN-slug, the feature's branch
SCOPE=${FEATURE_NAME%%-*}                      # NNN, the commit scope
BRANCH=$(git symbolic-ref --short HEAD)
if [ "$FROM" = specify ]; then
	[ -f "$FEATURE_REL/brief.md" ] || { echo "converge-loop: --from specify needs $FEATURE_REL/brief.md" >&2; exit 2; }
	if git show-ref --verify --quiet "refs/heads/$FEATURE_NAME"; then
		echo "converge-loop: branch $FEATURE_NAME exists; specify's hook would refuse to create it" >&2
		exit 2
	fi
fi

if [ "$ATTENDED" = 1 ] && [ "$LOGINS" = 0 ]; then
	echo "converge-loop: --attended needs both node logins in local/.env for its live sessions" >&2
	exit 2
fi
# Attended, converge's tags take tier 2 as the sessions' (CONVERGE_TAGS above), and a live
# session reaches Infrahub too, so both Infrahub variables are required, not optional.
if [ "$ATTENDED" = 1 ] && [ "$TIER2" = 0 ]; then
	echo "converge-loop: --attended needs INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN in local/.env" >&2
	exit 2
fi
# A skip is an answer the attended session gave; unattended there is no one to have given it.
if [ -n "$(echo $SKIP_ARG)" ]; then
	[ "$ATTENDED" = 1 ] || { echo "converge-loop: --skip needs --attended" >&2; exit 2; }
	for id in $SKIP_ARG; do
		[[ $id =~ ^T[0-9]+$ ]] || { echo "converge-loop: --skip takes task IDs, not '$id'" >&2; exit 2; }
		grep -qE "^\s*- \[ \] $id\b" "$TASKS" ||
			{ echo "converge-loop: --skip $id is not an unchecked task of $TASKS" >&2; exit 2; }
	done
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

# Absolute, since a lane's session runs with its worktree as the working directory.
RUN_DIR="$PWD/local/converge-loop/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN_DIR"
SUMMARY="$RUN_DIR/summary.md"
EVENTS="$RUN_DIR/events.jsonl"
: > "$EVENTS"
ATT="$RUN_DIR/attended"
QUESTIONS="$ATT/questions.jsonl"
[ "$ATTENDED" = 0 ] || { mkdir -p "$ATT"; : > "$QUESTIONS"; }

# tasks.md merges back from a lane by its ticks and notes alone (.gitattributes names the
# driver `tasks`; scripts/merge-tasks.py is it). The config is this clone's, so every
# worktree shares it; a clone without it meets a plain conflict, which is safe.
git config --local merge.tasks.name "tasks.md: ticks and notes alone (scripts/merge-tasks.py)"
git config --local merge.tasks.driver "python3 -I scripts/merge-tasks.py %O %A %B"

say() { printf '%s\n' "$*" | tee -a "$SUMMARY"; }

# One JSON line per event in $EVENTS, which the attended session watches (docs/development.md,
# "The attended loop"): `event <kind> key=value ...`; every value is a string.
event() {
	local kind="$1"
	shift
	python3 -c 'import json, sys, datetime
d = {"kind": sys.argv[1], "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
for kv in sys.argv[2:]:
    k, _, v = kv.partition("=")
    d[k] = v
print(json.dumps(d))' "$kind" "$@" >> "$EVENTS"
}

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
run_claude() { # <stage> <out file> <prompt> [live]
	local stage="$1" out="$2" prompt="$3" live="${4:-}" sid transcript status=0
	local model="${MODEL[$stage]}" effort="${EFFORT[$stage]}"
	local -a strip=(-u FYLGJA_SRLINUX_USERNAME -u FYLGJA_SRLINUX_PASSWORD -u FYLGJA_EOS_USERNAME -u FYLGJA_EOS_PASSWORD)
	local -a session
	local budget="$BUDGET_USD"
	if [ "$live" = live ]; then strip=(); budget="$LIVE_BUDGET_USD"; fi
	if [ -n "$RESUME_SID" ]; then
		sid="$RESUME_SID"
		session=(--resume "$sid")
		RESUME_SID=""
	else
		sid=$(python3 -c 'import uuid; print(uuid.uuid4())')
		session=(--session-id "$sid")
	fi
	LAST_SID="$sid"
	SESSION_HEAD=$(git rev-parse HEAD)
	if [ "$DRY_RUN" = 1 ]; then
		dry_run_session "$out" "$prompt" || status=$?
	else
		env "${strip[@]}" \
			claude -p "${session[@]}" --model "$model" --effort "$effort" \
			--permission-mode auto --max-budget-usd "$budget" "$prompt" \
			< /dev/null > "$out" 2>&1 || status=$?
		# From the working directory, a lane's worktree included: the hook then reads that
		# tree's tasks.md for the task delta and writes the pending file this tree shares.
		transcript=$(ls "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1 || true)
		if [ -n "$transcript" ]; then
			printf '{"session_id":"%s","transcript_path":"%s"}' "$sid" "$transcript" |
				CLAUDE_PROJECT_DIR="$PWD" python3 .claude/hooks/command-log.py stop > /dev/null || true
		fi
	fi
	say "  session $sid, $model $effort${live:+ ($live, budget \$$budget)}, exit $status, report $out"
	event session stage="$stage" label="$RUN_LABEL" tasks="$RUN_IDS" sid="$sid" model="$model" effort="$effort" live="${live:-}" exit="$status" report="$out" cwd="$PWD"
	return "$status"
}

# --dry-run's stand-in for a session, so the loop's mechanics run on a throwaway spec with
# no model: an implement run ticks its tasks (RUN_IDS), writes one note file per task and
# commits, as a session would; a task whose text says DRY-FAIL stays unchecked, so the
# question path runs, and one saying DRY-CONFLICT also rewrites the Notes heading, so two
# lanes meet a conflict the merge driver may not resolve; a converge pass appends nothing.
dry_run_session() { # <out file> <prompt>
	local out="$1" prompt="$2" tasks="$FEATURE_REL/tasks.md" id ticked="" n
	case "$prompt" in
	/speckit-converge*)
		printf 'Dry run: convergence pass, nothing appended.\n' > "$out"
		return 0 ;;
	/speckit-specify*)
		# The hook's work, by hand: the branch, the pointer, a spec and its checklist.
		git checkout -q -b "$FEATURE_NAME"
		printf '{\n  "feature_directory": "%s"\n}\n' "$FEATURE_REL" > .specify/feature.json
		mkdir -p "$FEATURE_REL/checklists"
		printf '# Feature Specification: dry run\n\n## User Scenarios & Testing\n\nOne story.\n\n## Requirements\n\n- **FR-001**: the file exists.\n\n## Success Criteria\n\n- **SC-001**: one read confirms it.\n' > "$FEATURE_REL/spec.md"
		printf '# Specification Quality Checklist\n\n- [x] All mandatory sections completed\n- [x] No [NEEDS CLARIFICATION] markers remain\n' > "$FEATURE_REL/checklists/requirements.md"
		printf 'Dry run: spec.md and its checklist written on branch %s.\n' "$FEATURE_NAME" > "$out"
		return 0 ;;
	/speckit-clarify*)
		printf 'Dry run: nothing to ask.\n\nCLARIFY-DONE\n' > "$out"
		return 0 ;;
	/speckit-plan*)
		printf '# Implementation Plan: dry run\n\n## Constitution Check\n\n| # | Gate | Status |\n|---|---|---|\n' > "$FEATURE_REL/plan.md"
		for n in I II III IV V VI VII VIII IX X XI; do printf '| %s | the gate | **PASS** |\n' "$n" >> "$FEATURE_REL/plan.md"; done
		printf '# research.md\n\n## 1. Verified at plan\n\nNothing.\n\n## 2. Decisions\n\n- R-01: none.\n\n## 3. Drafted for the operator\n\nNone.\n\n## 4. Owed at implement\n\nNothing.\n' > "$FEATURE_REL/research.md"
		printf 'Dry run: plan.md and research.md written.\n' > "$out"
		return 0 ;;
	/speckit-tasks*)
		# A route the planner reads: the fixture beside the brief when there is one.
		if [ -f "$FEATURE_REL/dry-run/tasks.md" ]; then cp "$FEATURE_REL/dry-run/tasks.md" "$tasks"; else
			printf '# Tasks: dry run\n\n## Phase 1: Setup\n\n- [ ] T001 the baseline\n\n### Recommended route\n\n1. **Run 1** — the baseline (T001). Read first: Makefile. Only this; stop and report.\n\n## Notes\n' > "$tasks"
		fi
		printf 'Dry run: tasks.md written.\n' > "$out"
		return 0 ;;
	/speckit-analyze*)
		printf 'Dry run: nothing to fix.\n\nANALYZE-DONE\n' > "$out"
		return 0 ;;
	esac
	mkdir -p "$FEATURE_REL/notes"
	for id in $RUN_IDS; do
		grep -qE "^\s*- \[ \] $id\b.*DRY-FAIL" "$tasks" && continue
		printf 'dry run %s by %s\n' "$id" "$RUN_LABEL" > "$FEATURE_REL/notes/$id.md"
		if grep -qE "^\s*- \[ \] $id\b.*DRY-CONFLICT" "$tasks"; then
			sed -i "s/^## Notes.*/## Notes ($id)/" "$tasks"
		fi
		sed -i -E "s/^(\s*- )\[ \]( $id\b)/\1[X]\2/" "$tasks"
		ticked="$ticked $id"
	done
	printf 'Dry run of %s: ticked%s; the rest stays unchecked.\n' "$RUN_LABEL" "${ticked:- nothing}" > "$out"
	git add -A -- "$FEATURE_REL"
	git diff --cached --quiet || git commit -q -m "chore($SCOPE): dry run, $RUN_LABEL" -m "A stand-in for a session, by scripts/converge-loop.sh --dry-run." -m "$(trailer_for "${MODEL[implement]}")"
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

# Publish what the command-log hook kept for a session (command-log.py flush) into its
# commands/ directory. The directories are git-ignored here, so the flush commits nothing;
# it would refuse, exit 3, a tracked directory whose diff carries the token.
publish_log() { # <what the session was>
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
	event stopped outcome="$1" sentence="$3"
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
# OPEN holds the task ids of every question with no answer yet, from the moment it is asked, and SKIPPED those the attended session answered "skip" (left unchecked, with a note,
# for the operator); the planner leaves both out. ASKED holds every task id put to a
# question, so the asked tasks answered and still unchecked can be implemented before the
# next pass. QN numbers the questions from 1.
OPEN=""
SKIPPED="$(echo $SKIP_ARG)"
ASKED=""
QN=0

json_str() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

stop_requested() { [ "$ATTENDED" = 1 ] && [ -e "$ATT/stop" ]; }

# Put a question to the attended session and act on its verdict. Unattended, this is the
# "operator" stop it replaces. Returns on `continue` (the ids stay excluded) and after a
# `hold` has been answered; exits on `stop` or a stop flag. No verdict within the timeout is
# a `hold`: the attended session may be restarting, and a held loop runs and spends nothing.
ask() { # <kind> <label> <ids> <report or -> <sentence>
	local kind="$1" label="$2" ids="$3" report="$4" sentence="$5" verdict="" waited=0
	[ "$ATTENDED" = 1 ] || finish operator 2 "$sentence"
	QN=$((QN + 1))
	ASKED="$ASKED $ids"
	OPEN="$OPEN $ids"
	printf '{"id":%d,"kind":%s,"run":%s,"tasks":%s,"report":%s,"sentence":%s,"asked_at":%s}\n' \
		"$QN" "$(json_str "$kind")" "$(json_str "$label")" "$(json_str "$(echo $ids)")" \
		"$(json_str "$report")" "$(json_str "$sentence")" "$(json_str "$(date -u +%FT%TZ)")" >> "$QUESTIONS"
	say "- question $QN ($kind): $label, tasks $(echo $ids), report $report"
	say "  $sentence"
	event question id="$QN" kind="$kind" label="$label" tasks="$(echo $ids)" report="$report"
	while [ ! -s "$ATT/verdict-$QN" ] && [ "$waited" -lt "$VERDICT_TIMEOUT" ]; do
		stop_requested && finish operator 2 "The attended session asked the loop to stop while question $QN waited for a verdict."
		sleep 2
		waited=$((waited + 2))
	done
	if [ -s "$ATT/verdict-$QN" ]; then
		verdict=$(tr -d '[:space:]' < "$ATT/verdict-$QN")
		say "  verdict $QN: $verdict"
	else
		verdict=hold
		say "  no verdict $QN after ${VERDICT_TIMEOUT}s, taken as hold"
	fi
	case "$verdict" in
	continue) ;;
	hold)
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
	event paused head="$(git rev-parse --short "$head")"
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
	event resumed head="$(git rev-parse --short HEAD)" answered="$(echo $answered)" skipped="$(echo $skipped)"
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

# The prompt of an implement run. A lane (4th argument) is told to run the tests of the
# packages it touched rather than the whole tier, since two lanes' `make test` at once would
# trip tier 1's wall-time bound; the merged tree runs the whole tier once in the gates.
implement_prompt() { # <route line> <ids> <live clause> [lane]
	local tests="make build, make test and make lint"
	[ -z "${4:-}" ] || tests="make build and make lint, then go test of the packages you touched (the merged tree runs the whole tier)"
	echo "/speckit-implement $1
Loop run (scripts/converge-loop.sh). Only $(echo $2 | sed 's/ /, /g'); stop at the run's checkpoint and report, and do not start another run. $3, or a decision you cannot take from spec.md, plan.md, research.md or docs/decisions.md, stays unchecked and your report says what it needs. End with $tests. Then commit your work, the ticks in tasks.md included, on the current branch as conventional commits whose bodies say why, as docs/development.md's Conventions say (a golden re-baseline in a commit of its own). Never push."
}

# The pure gates, into <log>; returns their status.
gates() { # <log>
	{ make build && [[ $(file bin/fylgja) == *'statically linked'* ]] && make test && make lint; } > "$1" 2>&1
}

# After a run (or a merged group of lanes) has committed: the session checks, the stray-tick
# check against <ids>, the gates, the uncommitted-changes check, the diff and the golden
# check. Stops the loop at the first failure.
settle() { # <label> <ids> <report file> <checked before> <tree before>
	local label="$1" ids="$2" out="$3" before_checked="$4" before_tree="$5" after_tree stray gate_log moved
	check_session

	stray=$(comm -13 <(echo "$before_checked" | sort) <(checked_ids | sort) | grep -vxF -f <(echo "$ids" | tr ' ' '\n') || true)
	[ -z "$stray" ] || finish contract 2 "Implement of $label ticked tasks outside it: $(echo $stray)."

	say "- gates"
	gate_log="${out%.md}.gates.log"
	gates "$gate_log" || { event gates label="$label" outcome=fail log="$gate_log"; finish gate 1 "A gate failed after $label; see $gate_log."; }
	say "  build, static, test, lint: pass"
	event gates label="$label" outcome=pass log="$gate_log"

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
}

# What a run left unchecked becomes a question (attended) or the operator stop.
ask_unchecked() { # <label> <ids> <report file>
	local open="" id
	for id in $2; do
		grep -qE "^\s*- \[[xX]\] $id\b" "$TASKS" || open="$open $id"
	done
	[ -z "$open" ] || ask unchecked "$1" "$open" "$3" "Implement of $1 left$open unchecked; its report ($3) says why."
}

# Implement exactly <ids>, then check, gate and log it. Returns only when all is well, or
# when a question about what was left has a `continue` or an answered `hold`.
implement() { # <label> <ids> <prompt> <report file> [live]
	local label="$1" ids="$2" line="$3" out="$4" live="${5:-}" before_checked before_tree clause
	before_checked=$(checked_ids)
	before_tree=$(snapshot)
	clause="$IMPLEMENT_LIVE"
	[ "$live" != live ] || clause="$IMPLEMENT_LIVE_OK"
	say "- implement $label${live:+ ($live)}: $(echo $ids)"
	RUN_LABEL="$label"
	RUN_IDS="$(echo $ids)"
	local kind=implement
	if [ "$live" = live ]; then kind=implement-live; elif [[ $label == pass* || $label == answered* ]]; then kind=implement-appended; fi
	run_claude "$kind" "$out" "$(implement_prompt "$line" "$ids" "$clause")" ${live:+"$live"} ||
		{ publish_log "$label"; finish error 1 "The implement session failed; its report is $out."; }
	publish_log "$label"
	settle "$label" "$ids" "$out" "$before_checked" "$before_tree"
	ask_unchecked "$label" "$ids" "$out"
}

# --- Lanes -------------------------------------------------------------------------------

# A worktree for one lane, on a new branch from HEAD, seeded with what Spec Kit needs and
# this repository ignores: directories by symlink, files by copy (git refuses a symlinked
# .gitignore), top-level entries only; local/ with the credentials file and the command
# log's two directories linked, so the hook writes the pending file this tree reads; and
# feature.json naming the feature. The seeded paths are listed in <seeded>, so the lane's
# dirty check can leave them out: a symlink matches no ignore rule that ends in "/".
seed_worktree() { # <worktree> <branch> <seeded list file>
	local wt="$1" branch="$2" seeded="$3" p
	git worktree add -q -b "$branch" "$wt" HEAD
	: > "$seeded"
	git ls-files -z --others --ignored --exclude-standard --directory -- .claude/skills .specify .venv |
		python3 -c 'import sys
ps = [p for p in sys.stdin.read().split("\0") if p]
ps.sort(key=lambda p: (p.rstrip("/").count("/"), p))
keep = []
for p in ps:
    if any(p.startswith(k) for k in keep if k.endswith("/")):
        continue
    keep.append(p)
sys.stdout.write("\0".join(keep))' |
		while IFS= read -r -d '' p; do
			mkdir -p "$wt/$(dirname "$p")"
			if [[ $p == */ ]]; then
				ln -s "$PWD/${p%/}" "$wt/${p%/}"
			else
				cp "$PWD/$p" "$wt/$p"
			fi
			printf '%s\n' "${p%/}" >> "$seeded"
		done
	mkdir -p "$wt/local" local/.command-start local/command-log
	[ ! -f local/.env ] || ln -s "$PWD/local/.env" "$wt/local/.env"
	ln -s "$PWD/local/.command-start" "$wt/local/.command-start"
	ln -s "$PWD/local/command-log" "$wt/local/command-log"
	printf '{\n  "feature_directory": "%s"\n}\n' "$FEATURE_REL" > "$wt/.specify/feature.json"
	grep -qx '.specify/feature.json' "$seeded" || echo '.specify/feature.json' >> "$seeded"
}

# Merge one lane's branch back, in this tree, and remove its worktree and branch. A merge
# that does not resolve mechanically (tasks.md's driver settles ticks and notes alone) is
# aborted and stops the loop at "merge", the worktree and branch kept for the operator.
merge_lane() { # <label> <worktree> <branch> <seeded list file>
	local label="$1" wt="$2" branch="$3" seeded="$4" dirty log="$RUN_DIR/${2##*/}.merge.log"
	dirty=$(git -C "$wt" status --porcelain --untracked-files=all | grep -vxF -f <(sed 's/^/?? /' "$seeded") || true)
	if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$dirty" ]; then
		finish contract 2 "Lane $label left uncommitted changes in $wt: $(echo "$dirty" | tr '\n' ' ')"
	fi
	if git merge --no-ff -q -m "merge($SCOPE): $label" \
		-m "Lane $label, built in its own worktree on branch $branch and merged back by scripts/converge-loop.sh in route order; tasks.md by scripts/merge-tasks.py, ticks and notes alone." \
		-m "$(trailer_for "${MODEL[implement]}")" "$branch" > "$log" 2>&1; then
		say "  merged $label at $(git rev-parse --short HEAD)"
		event merge label="$label" outcome=merged head="$(git rev-parse --short HEAD)"
		git worktree remove --force "$wt"
		git branch -q -d "$branch"
	else
		git merge --abort 2> /dev/null || true
		event merge label="$label" outcome=conflict log="$log"
		finish merge 2 "Lane $label's branch $branch does not merge back mechanically (see $log). Its worktree $wt is kept: merge it by hand (git merge $branch), commit, remove the worktree and the branch, then run the loop again."
	fi
}

# Implement a group of runs at once, one lane each, then merge them back in route order and
# settle the merged tree once. Each argument is one planner row (label, live, ids, lane,
# line, tab-separated). A lane's session runs in its worktree, so its `say` and `event` lines
# land in this run's files by their absolute paths, and its command-log entry is kept by the
# hook in the pending file this tree shares.
implement_lanes() { # <row>...
	local -a labels=() idss=() outs=() wts=() branches=() pids=()
	local row label live ids lane line slug wt before_checked before_tree all_ids="" i status
	before_checked=$(checked_ids)
	before_tree=$(snapshot)
	SESSION_HEAD=$(git rev-parse HEAD)
	for row in "$@"; do
		IFS=$'\t' read -r label live ids lane line <<< "$row"
		slug=$(echo "$label" | tr 'A-Z ' 'a-z-')
		wt="$PWD/local/lanes/$slug"
		labels+=("$label")
		idss+=("$(echo $ids)")
		outs+=("$RUN_DIR/$slug.implement.md")
		wts+=("$wt")
		branches+=("lane/$slug")
		all_ids="$all_ids $ids"
		say "- lane $label: $(echo $ids), worktree $wt"
		seed_worktree "$wt" "lane/$slug" "$RUN_DIR/$slug.seeded"
	done
	i=0
	for row in "$@"; do
		IFS=$'\t' read -r label live ids lane line <<< "$row"
		(
			cd "${wts[$i]}" || exit 1
			RUN_LABEL="$label"
			RUN_IDS="$(echo $ids)"
			status=0
			run_claude implement "${outs[$i]}" "$(implement_prompt "$line" "$ids" "$IMPLEMENT_LIVE" lane)" || status=$?
			echo "$status" > "${outs[$i]}.status"
		) &
		pids+=($!)
		i=$((i + 1))
	done
	for i in "${!pids[@]}"; do
		wait "${pids[$i]}" || true
	done
	for i in "${!labels[@]}"; do
		publish_log "${labels[$i]}"
		status=$(cat "${outs[$i]}.status" 2> /dev/null || echo 1)
		[ "$status" = 0 ] || finish error 1 "The implement session of ${labels[$i]} failed (exit $status); its report is ${outs[$i]}, and its worktree ${wts[$i]} is kept."
	done
	for i in "${!labels[@]}"; do
		merge_lane "${labels[$i]}" "${wts[$i]}" "${branches[$i]}" "$RUN_DIR/${wts[$i]##*/}.seeded"
	done
	settle "lanes ${labels[*]}" "$(echo $all_ids)" "${outs[0]}" "$before_checked" "$before_tree"
	for i in "${!labels[@]}"; do
		ask_unchecked "${labels[$i]}" "${idss[$i]}" "${outs[$i]}"
	done
}

# The planned runs, as TSV rows (scripts/converge-plan.py): label, 1 if the run needs the
# host (live), its unchecked IDs, its lane partner's label or nothing, and its line.
planned_runs() { # [<ids>]
	python3 -I scripts/converge-plan.py "$TASKS" "$TIER2" "$OPEN $SKIPPED" "${1:-}"
}

# The head run's lane group: itself and the partners that name each other, up to --lanes.
lane_group() { # <head row> [<ids>]
	local -a rows=("$1")
	local partner prow r
	IFS=$'\t' read -r _ _ _ partner _ <<< "$1"
	while [ "$partner" != - ] && [ "${#rows[@]}" -lt "$LANES" ]; do
		prow=$(planned_runs "${2:-}" | awk -F'\t' -v l="$partner" '$1 == l')
		[ -n "$prow" ] || break
		rows+=("$prow")
		IFS=$'\t' read -r _ _ _ partner _ <<< "$prow"
		for r in "${rows[@]}"; do
			[ "${r%%$'\t'*}" != "$partner" ] || partner=-
		done
	done
	printf '%s\n' "${rows[@]}"
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
say "Stages $FROM to $TO. Models: specify ${MODEL[specify]} ${EFFORT[specify]}, plan ${MODEL[plan]} ${EFFORT[plan]}, tasks ${MODEL[tasks]} ${EFFORT[tasks]}, analyze ${MODEL[analyze]} ${EFFORT[analyze]}, implement ${MODEL[implement]} ${EFFORT[implement]} (live and appended runs ${EFFORT[implement-live]}), converge ${MODEL[converge]} ${EFFORT[converge]}; at most $MAX_PASSES passes, \$$BUDGET_USD per session, $LANES lanes."
if [ "$TIER2" = 1 ] && [ "$ATTENDED" = 1 ]; then
	say "Tier 2: the sessions have Infrahub's address and token (local/.env); the node logins go to live sessions alone."
elif [ "$TIER2" = 1 ]; then
	say "Tier 2: the sessions have Infrahub's address and token (local/.env); never the node logins."
else
	say "Tier 2: the sessions have no Infrahub credentials, so tier 2 is the operator's."
fi
if [ "$ATTENDED" = 1 ]; then
	say "Attended: questions in $QUESTIONS, verdicts and flags in $ATT/, live sessions at \$$LIVE_BUDGET_USD, verdicts within ${VERDICT_TIMEOUT}s or held."
	[ -z "$SKIPPED" ] || say "Skipped from the start, left for the operator: $SKIPPED."
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
		IFS=$'\t' read -r label live ids lane line <<< "$run"
		say ""
		say "### $line"
		slug=$(echo "$label" | tr 'A-Z ' 'a-z-')
		if [ "$live" = 1 ]; then
			if [ "$ATTENDED" = 1 ]; then
				implement "$label" "$ids" "$line" "$RUN_DIR/$slug.implement.md" live
			else
				finish operator 2 "$label is the operator's (live infrastructure, or tagged [operator]): ${line%.}. Do it by hand, tick its tasks, commit, and run the loop again."
			fi
		elif [ "$lane" != - ] && [ "$LANES" -gt 1 ]; then
			mapfile -t group < <(lane_group "$run" "$only")
			if [ "${#group[@]}" -gt 1 ]; then
				implement_lanes "${group[@]}"
			else
				implement "$label" "$ids" "$line" "$RUN_DIR/$slug.implement.md"
			fi
		else
			implement "$label" "$ids" "$line" "$RUN_DIR/$slug.implement.md"
		fi
	done
	return "$none"
}

# --- The chain's first five stages ----------------------------------------------------
#
# Each stage: one session, a check that it wrote inside the feature directory alone, its
# gate on the tree, a commit of the directory, the command log. A stage that cannot go on
# without the operator asks a text question (attended) or stops the loop.

# Commit the feature directory as a stage's artifacts, when it changed.
stage_commit() { # <stage>
	git add -A -- "$FEATURE_REL"
	git diff --cached --quiet && return 0
	if git diff --cached | carries_token; then
		git reset -q -- "$FEATURE_REL"
		finish contract 2 "/speckit-$1's artifacts carry the value of INFRAHUB_API_TOKEN, so they were not committed. Remove it from $FEATURE_REL before anything else."
	fi
	git commit -q -m "docs($SCOPE): $1" \
		-m "Written by /speckit-$1, run headless by scripts/converge-loop.sh as one stage of the feature chain (docs/development.md, The feature chain)." \
		-m "$(trailer_for "${MODEL[$1]}")"
	say "  committed $(git rev-parse --short HEAD) ($1)"
}

# A stage writes inside the feature directory and nowhere else.
stage_writes() { # <stage>
	local stray
	stray=$(git status --porcelain | grep -vE "^.. (\"?)$FEATURE_REL/" || true)
	[ -z "$stray" ] || finish contract 2 "/speckit-$1 wrote outside $FEATURE_REL: $(echo "$stray" | tr '\n' ' ')"
}

# A question whose answer is text: clarify's and analyze's. Attended, the attended session
# puts the report's questions to the operator and writes the reply to reply-<n>; a
# skip-<n> means "take your own recommendations". Unattended it is the operator stop.
# Prints the reply.
ask_text() { # <kind> <label> <report> <sentence>
	local kind="$1" label="$2" report="$3" sentence="$4"
	[ "$ATTENDED" = 1 ] || finish operator 2 "$sentence"
	QN=$((QN + 1))
	printf '{"id":%d,"kind":%s,"run":%s,"tasks":"","report":%s,"sentence":%s,"asked_at":%s}\n' \
		"$QN" "$(json_str "$kind")" "$(json_str "$label")" "$(json_str "$report")" "$(json_str "$sentence")" "$(json_str "$(date -u +%FT%TZ)")" >> "$QUESTIONS"
	say "- question $QN ($kind): $label, report $report"
	say "  $sentence"
	event question id="$QN" kind="$kind" label="$label" tasks="" report="$report"
	while [ ! -s "$ATT/reply-$QN" ] && [ ! -e "$ATT/skip-$QN" ]; do
		stop_requested && finish operator 2 "The attended session asked the loop to stop while question $QN waited for its reply."
		sleep 5
	done
	if [ -e "$ATT/skip-$QN" ]; then
		mv "$ATT/skip-$QN" "$ATT/skipped-$QN"
		say "  question $QN skipped: the session takes its own recommendations"
		echo "No answer from the operator: take your own recommendations and go on."
	else
		say "  reply $QN received"
		cp "$ATT/reply-$QN" "$ATT/answered-$QN"
		cat "$ATT/reply-$QN"
	fi
}

# A stage that may end asking (clarify, analyze): run it, and while its report ends with
# <wait marker>, put the questions to the operator and resume the session with the reply.
stage_dialogue() { # <stage> <first prompt> <wait marker> <done marker>
	local stage="$1" prompt="$2" wait="$3" done_="$4" n=0 out reply
	RUN_LABEL="$stage"
	RUN_IDS=""
	while :; do
		n=$((n + 1))
		out="$RUN_DIR/$stage-$n.md"
		run_claude "$stage" "$out" "$prompt" || { publish_log "$stage"; finish error 1 "The $stage session failed; its report is $out."; }
		publish_log "$stage"
		if grep -q "^$done_" "$out"; then
			return 0
		elif grep -q "^$wait" "$out"; then
			reply=$(ask_text "$stage" "$stage $n" "$out" "/speckit-$stage asks the operator; its report ($out) holds the questions and its recommendations.")
			RESUME_SID="$LAST_SID"
			prompt="The operator's answers to your questions follow. Record each where /speckit-$stage records an answer, then end your turn with the line $done_, or with $wait above any question still open.

$reply"
		else
			finish contract 2 "/speckit-$stage ended with neither $done_ nor $wait; its report is $out."
		fi
	done
}

stage_specify() {
	local prompt
	# shellcheck disable=SC2016  # sed's $ is its last-line address
	prompt=$(sed -n '/^```$/,/^```$/p' "$FEATURE_REL/brief.md" | sed '1d;$d' | head -1)
	[ -n "$prompt" ] || finish error 1 "$FEATURE_REL/brief.md has no fenced prompt for specify."
	say ""
	say "## specify"
	RUN_LABEL=specify
	RUN_IDS=""
	run_claude specify "$RUN_DIR/specify.md" "/speckit-specify $prompt
Headless (scripts/converge-loop.sh): ask nothing, since the brief settles every decision; take its Decided section as given and its Open section as empty; do not commit and do not push." ||
		{ publish_log specify; finish error 1 "The specify session failed; its report is $RUN_DIR/specify.md."; }
	publish_log specify
	# The hook created the branch inside the session and fetched origin once: read both.
	BRANCH=$(git symbolic-ref --short HEAD)
	[ "$BRANCH" = "$FEATURE_NAME" ] || finish contract 2 "specify left the tree on branch $BRANCH, not $FEATURE_NAME."
	grep -q "\"feature_directory\": *\"$FEATURE_REL\"" .specify/feature.json 2> /dev/null ||
		finish contract 2 ".specify/feature.json does not name $FEATURE_REL after specify."
	REMOTE_REFS=$(remote_refs)
	say "  on branch $BRANCH; remote refs re-read after the hook's fetch"
	check_session
	[ -f "$FEATURE_REL/spec.md" ] || finish gate 1 "specify wrote no $FEATURE_REL/spec.md."
	! grep -q 'NEEDS CLARIFICATION' "$FEATURE_REL/spec.md" || finish gate 1 "$FEATURE_REL/spec.md carries a NEEDS CLARIFICATION marker; the brief should have settled it."
	! grep -qE '^- \[ \]' "$FEATURE_REL"/checklists/*.md 2> /dev/null || finish gate 1 "A checklist under $FEATURE_REL/checklists/ has an open box."
	stage_writes specify
	stage_commit specify
	event stage stage=specify outcome=pass
}

stage_clarify() {
	say ""
	say "## clarify"
	RESUME_SID="${SPECIFY_SID:-}"
	stage_dialogue clarify "/speckit-clarify Headless (scripts/converge-loop.sh): you cannot ask interactively. Run your coverage scan; if you would ask questions, write them all in one report under '## Questions', each with its options and your recommendation, and end your turn with the line CLARIFY-WAIT; if none, record the coverage summary in the spec as the command does and end your turn with the line CLARIFY-DONE. Do not commit." CLARIFY-WAIT CLARIFY-DONE
	check_session
	! grep -qE '^- \[ \]' "$FEATURE_REL"/checklists/*.md 2> /dev/null || finish gate 1 "A checklist under $FEATURE_REL/checklists/ has an open box after clarify."
	stage_writes clarify
	stage_commit clarify
	event stage stage=clarify outcome=pass
}

stage_plan() {
	say ""
	say "## plan"
	RUN_LABEL=plan
	RUN_IDS=""
	run_claude plan "$RUN_DIR/plan.md" "/speckit-plan Headless (scripts/converge-loop.sh): ask nothing; the brief and the spec settle the decisions, and what they leave to the plan is yours. Write research.md, data-model.md and quickstart.md to the section lists in docs/templates/research-template.md, docs/templates/data-model-template.md and docs/templates/quickstart-template.md. Verify against the running system where the brief leaves a fact to the plan, and load the Infrahub skill the brief names before writing data-model.md. Do not commit." ||
		{ publish_log plan; finish error 1 "The plan session failed; its report is $RUN_DIR/plan.md."; }
	publish_log plan
	check_session
	[ -f "$FEATURE_REL/plan.md" ] && [ -f "$FEATURE_REL/research.md" ] || finish gate 1 "plan wrote no plan.md or research.md under $FEATURE_REL."
	[ "$(grep -cE '^\| (I|II|III|IV|V|VI|VII|VIII|IX|X|XI) \|.*\| *\|$' "$FEATURE_REL/plan.md")" = 0 ] ||
		finish gate 1 "$FEATURE_REL/plan.md's Constitution Check has a row with no Status."
	! grep -q 'NEEDS CLARIFICATION' "$FEATURE_REL/plan.md" || finish gate 1 "$FEATURE_REL/plan.md carries a NEEDS CLARIFICATION marker."
	[ "$(grep -cE '^## [1-5]\. ' "$FEATURE_REL/research.md")" -ge 4 ] ||
		finish gate 1 "$FEATURE_REL/research.md lacks the template's numbered sections (docs/templates/research-template.md)."
	stage_writes plan
	stage_commit plan
	event stage stage=plan outcome=pass
}

# tasks.md as the loop needs it: a route the planner reads whole, Read first on every
# line, a reason on every [operator] task.
tasks_gate() { # <after what>
	local rows phases bare noread
	[ -f "$TASKS" ] || finish gate 1 "No $FEATURE_REL/tasks.md after $1."
	rows=$(planned_runs)
	[ -n "$rows" ] || finish gate 1 "$FEATURE_REL/tasks.md has no run to implement after $1."
	phases=$(awk -F'\t' '$1 ~ /^Phase/ {print $1 ": " $3}' <<< "$rows")
	[ -z "$phases" ] || finish gate 1 "$FEATURE_REL/tasks.md's route does not name every unchecked task after $1: $(echo "$phases" | tr '\n' ';')"
	noread=$(grep -E '^\s*[0-9]+\.\s+\*\*Run [0-9]+\*\*' "$TASKS" | grep -vE '\[(operator|live)\]' | grep -v 'Read first:' | grep -oE 'Run [0-9]+' || true)
	[ -z "$noread" ] || finish gate 1 "Route lines without 'Read first:' after $1: $(echo $noread | sed 's/ /, /g')."
	bare=$(grep -E '^\s*- \[ \] T[0-9]+ \[operator\]' "$TASKS" | grep -vE '\b(since|because)\b' | grep -oE 'T[0-9]+' || true)
	[ -z "$bare" ] || finish gate 1 "[operator] tasks without a reason (since …, because …) after $1: $(echo $bare | sed 's/ /, /g')."
	say "  tasks.md: $(grep -cE '^\s*- \[ \] T[0-9]+' "$TASKS") open tasks in $(wc -l <<< "$rows") runs; [operator]: $(grep -cE '^\s*- \[ \] T[0-9]+ \[operator\]' "$TASKS")"
}

stage_tasks() {
	say ""
	say "## tasks"
	RUN_LABEL=tasks
	RUN_IDS=""
	run_claude tasks "$RUN_DIR/tasks.md" "/speckit-tasks Headless (scripts/converge-loop.sh): ask nothing. Follow the template's rules (.specify/templates/overrides/tasks-template.md): a run is the tasks that share one context, its ids need not be contiguous, every route line names what to read first, lane marks follow the lane rule, and an [operator] task is allowed only where it could not precede the chain, with its reason on its line (since …, because …). A loop run commits its own work. Do not commit." ||
		{ publish_log tasks; finish error 1 "The tasks session failed; its report is $RUN_DIR/tasks.md."; }
	publish_log tasks
	check_session
	tasks_gate tasks
	stage_writes tasks
	stage_commit tasks
	event stage stage=tasks outcome=pass
}

stage_analyze() {
	say ""
	say "## analyze"
	stage_dialogue analyze "/speckit-analyze Headless (scripts/converge-loop.sh): you cannot ask interactively. Write the read-only report first; then apply every fix that spec.md, plan.md, research.md, the brief and docs/decisions.md settle, judging each [operator] task (drop or re-tag one the artifacts already settle; keep one that is necessary, with its reason on its line); list what needs the operator under '## For the operator', each with its options and your recommendation, and end your turn with the line ANALYZE-WAIT; with nothing for the operator, end with the line ANALYZE-DONE. Do not commit." ANALYZE-WAIT ANALYZE-DONE
	check_session
	tasks_gate analyze
	stage_writes analyze
	stage_commit analyze
	event stage stage=analyze outcome=pass
}

SPECIFY_SID=""
if runs_stage specify; then stage_specify; SPECIFY_SID="$LAST_SID"; fi
! runs_stage clarify || stage_clarify
! runs_stage plan || stage_plan
! runs_stage tasks || stage_tasks
! runs_stage analyze || stage_analyze
[ "$TO_I" -ge "$IMPLEMENT_I" ] || finish "done" 0 "The stages $FROM to $TO ran."
[ -f "$TASKS" ] || finish error 1 "No tasks.md at $TASKS."

if runs_stage implement; then
	say ""
	say "## Planned runs"
	run_planned || say "Every planned task is checked."
fi

runs_stage converge || finish planned 0 "Every planned run is implemented; convergence was not asked for."

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
	RUN_LABEL="pass $pass"
	RUN_IDS=""
	run_claude converge "$RUN_DIR/pass-$pass.converge.md" "/speckit-converge Loop pass $pass (scripts/converge-loop.sh). Tag every task you append directly after its ID with exactly one of: $CONVERGE_TAGS. The append contract is otherwise unchanged; do not commit." ||
		{ publish_log "convergence pass $pass"; finish error 1 "The converge session failed; its report is $RUN_DIR/pass-$pass.converge.md."; }
	check_session

	after_tree=$(snapshot)
	stray=$(git diff --name-only "$before_tree" "$after_tree" |
		grep -vxF "$FEATURE_REL/tasks.md" | grep -vE "^$FEATURE_REL/commands/" || true)
	[ -z "$stray" ] || finish contract 2 "Converge wrote outside tasks.md: $(echo "$stray" | tr '\n' ' ')"
	cmp -s -n "$(stat -c%s "$before_tasks")" "$before_tasks" "$TASKS" ||
		finish contract 2 "Converge changed tasks.md above its new phase: diff $before_tasks $TASKS"

	if cmp -s "$before_tasks" "$TASKS"; then
		publish_log "convergence pass $pass"
		event pass pass="$pass" appended=""
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
		-m "Found by /speckit-converge, run $([ "$ATTENDED" = 1 ] && echo attended || echo unattended) by scripts/converge-loop.sh against the tree at $(git rev-parse --short HEAD). The phase names each gap with its evidence; the tags decide the stopping rule and whether the loop may implement them:$tags" \
		-m "$(trailer_for "${MODEL[converge]}")" -- "$TASKS"
	say "  committed $(git rev-parse --short HEAD) (the phase)"
	event pass pass="$pass" appended="$(echo $ids)" tags="$(echo "$tags" | tr '\n' ' ')" head="$(git rev-parse --short HEAD)"
	publish_log "convergence pass $pass"

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
