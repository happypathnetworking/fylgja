"""Where the attended loop stands, read from disk alone (docs/development.md, "The attended loop").

python3 -I .claude/skills/converge-loop/state.py           the current run: its state, each run's
                                                            last session and report, any lane
                                                            worktree kept, every question and what
                                                            each still needs
python3 -I .claude/skills/converge-loop/state.py --carry   the task IDs the feature's latest
                                                            run skipped that are still unchecked,
                                                            for scripts/converge-loop.sh --skip
--feature specs/NNN-slug names the feature in place of .specify/feature.json (a chain started
at specify, before the pointer moved). --run local/converge-loop/<started> reads that run
instead of the newest.

The run is the newest directory under local/converge-loop/ with an attended/ whose summary
names the feature. Reads only; writes nothing but the lock file's inode when it is absent,
as flock does.
"""

import datetime
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                                   text=True, check=True).stdout.strip())
if "--feature" in sys.argv:
    FEATURE = sys.argv[sys.argv.index("--feature") + 1].rstrip("/")
else:
    FEATURE = json.loads((ROOT / ".specify/feature.json").read_text())["feature_directory"]
TASKS = ROOT / FEATURE / "tasks.md"


def runs():
    """The feature's attended runs, newest first."""
    base = ROOT / "local/converge-loop"
    out = []
    for d in sorted(base.glob("*/"), reverse=True) if base.exists() else []:
        s = d / "summary.md"
        if (d / "attended").is_dir() and s.exists() and s.read_text().startswith(f"# Converge loop, {FEATURE}\n"):
            out.append(d)
    return out


def jsonl(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def questions(run):
    return jsonl(run / "attended/questions.jsonl")


def events(run):
    return jsonl(run / "events.jsonl")


def unchecked():
    return set(re.findall(r"^\s*- \[ \] (T\d+)\b", TASKS.read_text(), re.M)) if TASKS.exists() else set()


def skipped(run):
    """Every task the run skipped: from the start (--skip) and by a skip-<n> it took."""
    ids = []
    m = re.search(r"^Skipped from the start, left for the operator: (.*)\.$", (run / "summary.md").read_text(), re.M)
    if m:
        ids += m.group(1).split()
    att = run / "attended"
    for q in questions(run):
        if q.get("tasks") and ((att / f"skipped-{q['id']}").exists() or (att / f"skip-{q['id']}").exists()):
            ids += q["tasks"].split()
    return list(dict.fromkeys(ids))


def loop_running():
    lock = ROOT / "local/converge-loop.lock"
    return subprocess.run(["flock", "-n", str(lock), "true"]).returncode != 0


def main():
    all_runs = runs()
    if "--carry" in sys.argv[1:]:
        if all_runs:
            todo = unchecked()
            print(" ".join(i for i in skipped(all_runs[0]) if i in todo))
        return
    if not all_runs:
        print(f"no attended run of {FEATURE} under local/converge-loop/")
        return
    run = ROOT / sys.argv[sys.argv.index("--run") + 1] if "--run" in sys.argv else all_runs[0]
    rel = run.relative_to(ROOT)
    att = run / "attended"
    flag = f"{rel}/attended"
    summary = (run / "summary.md").read_text()
    stopped = re.search(r"^## Stopped: (\S+)\n\n(.*)$", summary, re.M)
    running = loop_running()
    print(f"run: {rel}  (ATT={rel}/attended; events {rel}/events.jsonl)")
    print(f"loop process: {'running (holds local/converge-loop.lock)' if running else 'not running'}")
    if stopped:
        state = f"stopped: {stopped.group(1)}: {stopped.group(2)}"
    elif not running:
        state = "DEAD: no lock and no '## Stopped' line; the script was killed"
    elif (att / "paused").exists():
        state = "PAUSED: the tree is yours; land, commit, then touch answer-/skip- and resume"
    elif (att / "pause").exists():
        state = "pause requested; the script has not reached its between-sessions point"
    else:
        state = "running"
    print(f"state: {state}")

    # Each run's or stage's last session, with its report, so a report not yet shown can be.
    last = {}
    for e in events(run):
        if e.get("kind") == "session":
            last[e.get("label") or e.get("stage")] = e
    for label, e in last.items():
        print(f"  session {label}: {e.get('model')} {e.get('effort')}, exit {e.get('exit')}, report {e.get('report')}")
    kept = sorted(p for p in (ROOT / "local/lanes").glob("*/") if p.is_dir()) if (ROOT / "local/lanes").exists() else []
    for p in kept:
        print(f"  lane worktree kept: {p.relative_to(ROOT)} (branch lane/{p.name}; merge by hand, then remove)")

    now = datetime.datetime.now(datetime.timezone.utc)
    for q in questions(run):
        n = q["id"]
        text = q.get("kind") in ("clarify", "analyze")
        v = att / f"verdict-{n}"
        verdict = v.read_text().strip() if v.exists() and v.read_text().strip() else None
        if (att / f"answered-{n}").exists():
            fate = "answered" if not text else "replied"
        elif (att / f"skipped-{n}").exists():
            fate = "skipped"
        elif (att / f"answer-{n}").exists() or (att / f"skip-{n}").exists():
            fate = "answer flagged, awaiting resume"
        elif text:
            if stopped or not running:
                fate = "UNREPLIED at the stop: the stage must run again"
            else:
                age = int((now - datetime.datetime.fromisoformat(q["asked_at"].replace("Z", "+00:00"))).total_seconds())
                fate = f"NO REPLY ({age}s since asked): put the report's questions to the operator, then write {flag}/reply-{n} (or touch skip-{n})"
        elif stopped or not running:
            fate = "UNANSWERED at the stop: put it to the operator, land it without the handshake"
        elif re.search(rf"^  no verdict {n} after \d+s, taken as hold$", summary, re.M):
            fate = f"HELD ON SILENCE: ask the operator, land the reply, then {flag}/answer-{n} or skip-{n}"
        elif verdict is None:
            age = int((now - datetime.datetime.fromisoformat(q["asked_at"].replace("Z", "+00:00"))).total_seconds())
            fate = f"NO VERDICT ({age}s since asked): write {flag}/verdict-{n} now"
        else:
            fate = f"open: put it to the operator unless already asked; land the reply, then {flag}/answer-{n} or skip-{n}"
        print(f"  question {n} {q['kind']} {q['run']} [{q.get('tasks', '')}] verdict={verdict or '-'}: {fate}; report {q['report']}")
    if not questions(run):
        print("  no questions")
    tail = [l for l in summary.splitlines() if l.strip()][-1]
    print(f"last: {tail}")


main()
