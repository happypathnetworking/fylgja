#!/usr/bin/env python3
"""Spec Kit command log, driven by Claude Code hooks (.claude/settings.json).

  command-log.py start    UserPromptSubmit: snapshot git HEAD and tasks.md when a
                          /speckit-* command is typed, so the stop can diff them.
  command-log.py stop     Stop: read the session transcript and keep one entry per
                          /speckit-* command in local/command-log/pending.jsonl
                          (git-ignored), with the commands/ directory it belongs in.
  command-log.py flush [--commit] [--what TEXT] [--body TEXT]
                          Publish the pending entries: upsert each into its directory's
                          runs.jsonl (full record, report included) and log.md (prompt and
                          metrics) — <feature>/commands/, or commands/ at the repository
                          root when no feature resolved — and empty the pending file. With
                          --commit, commit each directory it touched as "docs(NNN): the
                          command log[ for TEXT]", unless the staged diff carries the value
                          of INFRAHUB_API_TOKEN (exit 3, nothing committed).
  command-log.py replay TRANSCRIPT [--out DIR]
                          Run the stop logic over a saved transcript straight into DIR's
                          commands/ directories (testing, backfill).

Stop fires after every turn, so a command that stops to ask the operator is rewritten
in place until it ends; the entry keeps the location its first write chose. It writes no
tracked file, so a turn that ends after a commit leaves the tree clean: the log reaches
git when it is flushed (`make command-log`, or scripts/converge-loop.sh after each
session and before it starts).

The transcript format is Claude Code's, undocumented (verified on 2.1.272). A field the
record depends on that is missing is reported as a problem, never written as zero.
"""
import collections
import contextlib
import datetime as dt
import fcntl
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
START_DIR = os.path.join(ROOT, "local", ".command-start")
PENDING_DIR = os.path.join(ROOT, "local", "command-log")
PENDING = os.path.join(PENDING_DIR, "pending.jsonl")
CMD_RE = re.compile(r"<command-name>(/speckit-[a-z-]+)</command-name>")
ARGS_RE = re.compile(r"<command-args>(.*)</command-args>", re.S)
IDE_RE = re.compile(r"<(ide_[a-z_]+)>.*?</\1>\s*", re.S)  # context the IDE prepends to a prompt
TASK_RE = re.compile(r"^\s*- \[([ xX])\] (T\d+)\b", re.M)
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(*args):
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def feature_dir():
    out = sh("bash", ".specify/scripts/bash/check-prerequisites.sh", "--paths-only")
    m = re.search(r"^FEATURE_DIR: (.+)$", out, re.M)
    return m.group(1).strip() if m and os.path.isdir(m.group(1).strip()) else None


def task_state(fdir):
    path = os.path.join(fdir, "tasks.md") if fdir else None
    if not path or not os.path.isfile(path):
        return None
    return {tid: mark != " " for mark, tid in TASK_RE.findall(open(path, encoding="utf-8").read())}


def read_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # a line still being written
    return rows


def user_text(row):
    """The text of a user row: a string, or (from the IDE) a list of text blocks. None for
    tool results."""
    c = (row.get("message") or {}).get("content")
    if row.get("type") != "user":
        return None
    if isinstance(c, str):
        return c
    if isinstance(c, list) and c and all(b.get("type") == "text" for b in c):
        return "\n".join(b.get("text", "") for b in c)
    return None


def is_operator_prompt(row):
    """A message the operator typed: not meta, not a tool result, not a harness notice."""
    c = user_text(row)
    return (c is not None and not row.get("isMeta") and not row.get("isSidechain")
            and not c.startswith(("<local-command", "<task-notification", "<command-name>/clear")))


# ---------------------------------------------------------------- metrics


class Usage:
    def __init__(self):
        self.by_request = {}  # requestId -> (model, usage); a request spans several rows

    def add(self, row):
        m = row.get("message") or {}
        u = m.get("usage")
        key = row.get("requestId") or m.get("id")
        if u and key:
            self.by_request[key] = (m.get("model"), u)

    def totals(self):
        tot = collections.Counter()
        per_model = collections.defaultdict(collections.Counter)
        for model, u in self.by_request.values():
            for k in USAGE_KEYS:
                tot[k] += u.get(k, 0)
                per_model[model][k] += u.get(k, 0)
            cc = u.get("cache_creation") or {}
            for k in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
                tot["cache_write_" + k.split("_")[1]] += cc.get(k, 0)
        return {"requests": len(self.by_request), **dict(tot),
                "by_model": {k: dict(v) for k, v in per_model.items()}}


def context_of(u, with_output):
    n = sum(u.get(k, 0) for k in USAGE_KEYS[:3])
    return n + (u.get("output_tokens", 0) if with_output else 0)


def req_id(r):
    return r.get("requestId") or (r.get("message") or {}).get("id")


def segments(span):
    """Split a command's rows at each prompt the operator typed. Segment 0 is the command
    itself; a background task waking the model stays in the segment it belongs to."""
    segs = [[span[0]]]
    for r in span[1:]:
        if is_operator_prompt(r):
            segs.append([r])
        else:
            segs[-1].append(r)
    return segs


def measure(segs, subagents):
    """Metrics over one or more segments. Time counts from each segment's prompt (or the
    previous segment's end, if the prompt was queued) to its last model response, so
    waiting on the operator between segments is never counted."""
    main, subs = Usage(), Usage()
    models, efforts, speeds = collections.Counter(), collections.Counter(), collections.Counter()
    tools, files = collections.Counter(), set()
    thinking_blocks = tool_errors = turns = 0
    report_req, report = None, []
    first_u = last_u = None
    peak, active, prev_end, bounds = 0, 0.0, None, []
    for seg in segs:
        assistant = [r for r in seg if r.get("type") == "assistant" and not r.get("isSidechain")]
        if not assistant:
            continue  # a prompt with no response yet
        start = ts(seg[0]["timestamp"])
        if prev_end and start < prev_end:
            start = prev_end
        end = ts(assistant[-1]["timestamp"])  # rows after it are the harness's housekeeping
        active += max(0.0, (end - start).total_seconds())
        prev_end = end
        bounds.append((start, end))
        for r in seg:
            m = r.get("message") or {}
            if r.get("type") == "assistant" and not r.get("isSidechain"):
                main.add(r)
                if m.get("model"):
                    models[m["model"]] += 1
                if r.get("perTurnEffort") or r.get("effort"):
                    efforts[r.get("perTurnEffort") or r.get("effort")] += 1
                if m.get("stop_reason") == "end_turn":
                    turns += 1
                u = m.get("usage")
                if u:
                    first_u = first_u or u
                    last_u = u
                    peak = max(peak, context_of(u, True))
                    if u.get("speed"):
                        speeds[u["speed"]] += 1
                for b in m.get("content") or []:
                    if b.get("type") == "thinking":
                        thinking_blocks += 1
                    elif b.get("type") == "tool_use":
                        tools[b.get("name")] += 1
                        inp = b.get("input") or {}
                        fp = inp.get("file_path") or inp.get("notebook_path")
                        if b.get("name") in EDIT_TOOLS and fp:
                            files.add(os.path.relpath(fp, ROOT) if fp.startswith(ROOT) else fp)
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        # The report is the text of the last response that had any.
                        if req_id(r) != report_req:
                            report_req, report = req_id(r), []
                        report.append(b["text"])
            elif r.get("type") == "user" and isinstance(m.get("content"), list):
                tool_errors += sum(1 for b in m["content"] if b.get("type") == "tool_result" and b.get("is_error"))
    if not bounds:
        return None
    for first_ts, rows in subagents:
        if any(s <= first_ts <= e for s, e in bounds):
            for r in rows:
                if r.get("type") == "assistant":
                    subs.add(r)
    return {
        "started_at": iso(bounds[0][0]),
        "ended_at": iso(bounds[-1][1]),
        "active_seconds": round(active),
        "wall_seconds": round((bounds[-1][1] - bounds[0][0]).total_seconds()),
        "segments": len(bounds),
        "turns": turns,
        "model": dict(models),
        "effort": dict(efforts),
        "speed": dict(speeds),
        "thinking_blocks": thinking_blocks,
        "context_tokens": {
            "before": context_of(first_u, False) if first_u else None,
            "after": context_of(last_u, True) if last_u else None,
            "peak": peak or None,
        },
        "tokens": main.totals(),
        "subagent_tokens": subs.totals() if subs.by_request else None,
        "tool_calls": dict(tools),
        "tool_errors": tool_errors,
        "files_edited": sorted(files),
        "report": "\n\n".join(report) or None,
    }


def build(cmd_row, span, subagents, start_snap, problems):
    cmd_text = user_text(cmd_row)
    args = ARGS_RE.search(cmd_text)
    segs = segments(span)
    total = measure(segs, subagents)
    if total is None:
        return None  # the command has not produced a response yet
    for field, present in (("model", total["model"]), ("usage", total["context_tokens"]["before"] is not None),
                           ("effort", total["effort"])):
        if not present:
            problems.append(f"no {field} on any assistant row")

    per_segment = []
    for i, seg in enumerate(segs):
        m = measure([seg], subagents)
        if m is None:
            continue
        prompt = (args.group(1) if args and args.group(1).strip() else None) if i == 0 else IDE_RE.sub("", user_text(seg[0]))
        per_segment.append({
            "index": i,
            "prompt": prompt,
            **{k: m[k] for k in ("started_at", "ended_at", "active_seconds", "model", "effort",
                                 "context_tokens", "tool_calls", "report")},
            "tokens": {k: v for k, v in m["tokens"].items() if k != "by_model"},
            "subagent_tokens": m["subagent_tokens"] and {k: v for k, v in m["subagent_tokens"].items() if k != "by_model"},
        })

    command = measure(segs[:1], subagents)
    follow_ups = measure(segs[1:], subagents) if len(segs) > 1 else None
    perm = collections.Counter(r.get("permissionMode") for r in span if r.get("permissionMode"))
    return {
        "id": cmd_row["uuid"],
        "name": CMD_RE.search(cmd_text).group(1),
        "session_id": cmd_row.get("sessionId"),
        "claude_code_version": cmd_row.get("version"),
        "started_at": total["started_at"],
        "ended_at": total["ended_at"],
        "permission_mode": dict(perm),
        "git_head_before": (start_snap or {}).get("git_head"),
        "git_head_after": sh("git", "rev-parse", "--short", "HEAD").strip() or None,
        # command: segment 0 alone, the number for estimates and model comparisons.
        # follow_ups: every later prompt the operator typed. total: the whole session.
        # For /speckit-clarify the operator's answers are follow-ups; use total there.
        "command": command,
        "follow_ups": follow_ups,
        "total": total,
        "segments": per_segment,
        "problems": problems,
    }


def task_delta(before, after):
    if before is None or after is None:
        return None
    return {
        "checked": sorted((t for t, done in after.items() if done and not before.get(t)), key=lambda t: int(t[1:])),
        "added": sorted((t for t in after if t not in before), key=lambda t: int(t[1:])),
    }


# ---------------------------------------------------------------- writing


def fmt_secs(s):
    h, rem = divmod(int(s), 3600)
    return f"{h}h{rem // 60:02d}m" if h else f"{rem // 60}m{rem % 60:02d}s"


def fmt_k(n):
    return "—" if n is None else (f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k")


def log_entry(rec):
    c = rec["command"]
    t, ctx = c["tokens"], c["context_tokens"]
    tasks = rec.get("tasks")
    lines = [
        f"<!-- run:{rec['id']} -->",
        f"## {rec['started_at']} `{rec['name']}`",
        "",
        "| | |",
        "|---|---|",
        f"| Model | {', '.join(c['model'])} · effort {', '.join(c['effort']) or '—'}"
        f"{' · fast' if 'fast' in c['speed'] else ''} |",
        f"| Time | {fmt_secs(c['active_seconds'])} active · {fmt_secs(c['wall_seconds'])} wall |",
        f"| Context | {fmt_k(ctx['before'])} → {fmt_k(ctx['after'])} (peak {fmt_k(ctx['peak'])}) |",
        f"| Tokens | {fmt_k(t.get('output_tokens'))} out · {fmt_k(t.get('input_tokens'))} in"
        f" · {fmt_k(t.get('cache_creation_input_tokens'))} cache write"
        f" · {fmt_k(t.get('cache_read_input_tokens'))} cache read · {t['requests']} requests |",
    ]
    if c.get("subagent_tokens"):
        s = c["subagent_tokens"]
        lines.append(f"| Subagents | {fmt_k(s.get('output_tokens'))} out"
                     f" · {fmt_k(s.get('cache_read_input_tokens'))} cache read · {s['requests']} requests |")
    f = rec["follow_ups"]
    if f:
        lines.append(f"| Follow-ups | {f['segments']} · +{fmt_secs(f['active_seconds'])} active"
                     f" · +{fmt_k(f['tokens'].get('output_tokens'))} out · context"
                     f" {fmt_k(rec['total']['context_tokens']['after'])} at the end |")
    if tasks and (tasks["checked"] or tasks["added"]):
        lines.append(f"| Tasks | {len(tasks['checked'])} checked · {len(tasks['added'])} added |")
    if rec["problems"]:
        lines.append(f"| Problems | {'; '.join(rec['problems'])} |")
    for s in rec["segments"]:
        lines.append("")
        if s["index"] > 0:
            lines.append(f"Follow-up {s['index']} ({s['started_at']}, {fmt_secs(s['active_seconds'])} active):")
            lines.append("")
        if s["prompt"]:
            lines += ["`````text", s["prompt"].rstrip("\n"), "`````"]
        else:
            lines.append("*(no prompt)*")
    lines.append(f"<!-- /run:{rec['id']} -->")
    return "\n".join(lines) + "\n"


def upsert_jsonl(path, rec):
    lines, found = [], False
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            if line.strip() and json.loads(line).get("id") == rec["id"]:
                line, found = json.dumps(rec, ensure_ascii=False) + "\n", True
            lines.append(line)
    if not found:
        lines.append(json.dumps(rec, ensure_ascii=False) + "\n")
    write_atomic(path, "".join(lines))


def upsert_log(path, rec, title):
    entry = log_entry(rec)
    body = open(path, encoding="utf-8").read() if os.path.isfile(path) else (
        f"# Command log — {title}\n\nSpec Kit commands, newest last: the prompt verbatim (fenced so it\n"
        "can be copied whole) and what the run cost. The full record, report included, is\n"
        "the matching line of `runs.jsonl`.\n")
    pat = re.compile(rf"<!-- run:{re.escape(rec['id'])} -->.*?<!-- /run:{re.escape(rec['id'])} -->\n", re.S)
    body = pat.sub(lambda _: entry, body) if pat.search(body) else body.rstrip("\n") + "\n\n" + entry
    write_atomic(path, body)


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def existing_dir(run_id, out_root):
    for p in glob.glob(os.path.join(out_root, "specs", "*", "commands", "runs.jsonl")) + [
            os.path.join(out_root, "commands", "runs.jsonl")]:
        if os.path.isfile(p) and f'"id": "{run_id}"' in open(p, encoding="utf-8").read():
            return os.path.dirname(p)
    return None


# ---------------------------------------------------------------- pending entries


@contextlib.contextmanager
def pending_lock():
    """Serialise every read-modify-write of the pending file: an interactive session's Stop
    and the loop's flush can run at once, and write_atomic's temporary name is shared."""
    os.makedirs(PENDING_DIR, exist_ok=True)
    with open(os.path.join(PENDING_DIR, ".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def read_pending():
    """{run id: {"target": dir relative to ROOT, "title": log title, "rec": record}}, in
    the order the entries were first kept."""
    return {p["rec"]["id"]: p for p in read_rows(PENDING)} if os.path.isfile(PENDING) else {}


def write_pending(pending):
    if pending:
        write_atomic(PENDING, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pending.values()))
    elif os.path.isfile(PENDING):
        os.remove(PENDING)


def git(*args):
    return subprocess.run(("git",) + args, cwd=ROOT, capture_output=True, text=True, timeout=60)


def api_token():
    """The Infrahub token, from the environment or local/.env, only to check that no
    commit carries it. Never printed."""
    token = os.environ.get("INFRAHUB_API_TOKEN")
    env = os.path.join(ROOT, "local", ".env")
    if not token and os.path.isfile(env):
        for line in open(env, encoding="utf-8"):
            m = re.match(r"\s*(?:export\s+)?INFRAHUB_API_TOKEN=(.*)$", line)
            if m:
                token = m.group(1).strip().strip("'\"")
    return token or None


def flush(commit, what, body):
    """Publish the pending entries into their commands/ directories, then, with commit,
    commit each directory touched. Returns 3 when a directory's diff carries the token."""
    with pending_lock():
        pending = read_pending()
        touched = []
        for p in pending.values():
            target = os.path.join(ROOT, p["target"])
            upsert_jsonl(os.path.join(target, "runs.jsonl"), p["rec"])
            upsert_log(os.path.join(target, "log.md"), p["rec"], p["title"])
            if p["target"] not in touched:
                touched.append(p["target"])
        write_pending({})
    if not commit:
        for rel in touched:
            print(f"published {rel}")
        return 0
    status, token = 0, api_token()
    for rel in touched:
        git("add", "--", rel)
        if git("diff", "--cached", "--quiet", "--", rel).returncode == 0:
            continue
        if token and token in git("diff", "--cached", "--", rel).stdout:
            git("reset", "-q", "--", rel)
            print(f"command-log: {rel} carries the value of INFRAHUB_API_TOKEN; nothing was committed",
                  file=sys.stderr)
            status = 3
            continue
        m = re.match(r"specs/(\d+)-", rel)
        subject = f"docs({m.group(1)}): the command log" if m else "docs: the command log"
        subject += f" for {what}" if what else ""
        r = git("commit", "-q", "-m", subject, "-m", body, "--", rel)
        if r.returncode != 0:
            print(f"command-log: committing {rel} failed: {r.stderr.strip()}", file=sys.stderr)
            return 1
        print(f"committed {git('rev-parse', '--short', 'HEAD').stdout.strip()} {rel}")
    return status


# ---------------------------------------------------------------- entry points


def spans(rows):
    """(command row, rows up to the next /speckit-* command) for each command."""
    idx = [i for i, r in enumerate(rows) if is_operator_prompt(r) and CMD_RE.search(user_text(r))]
    return [(rows[i], [r for r in rows[i:(idx[n + 1] if n + 1 < len(idx) else len(rows))] if r.get("timestamp")])
            for n, i in enumerate(idx)]


def record_transcript(transcript, out_root, only_last, pending=None):
    """Build each command's record. With pending (a read_pending dict, held under
    pending_lock), keep the records there; without, upsert them into out_root's files."""
    rows = read_rows(transcript)
    sub_dir = os.path.join(os.path.splitext(transcript)[0], "subagents")
    sub_files = sorted(glob.glob(os.path.join(sub_dir, "*.jsonl")))
    written = []
    all_spans = spans(rows)
    for cmd_row, span in (all_spans[-1:] if only_last else all_spans):
        subagents = []
        for f in sub_files:
            srows = [r for r in read_rows(f) if r.get("timestamp")]
            if srows:
                subagents.append((ts(srows[0]["timestamp"]), srows))
        snap_path = os.path.join(START_DIR, f"{cmd_row.get('sessionId')}.json")
        snap = json.load(open(snap_path)) if os.path.isfile(snap_path) else None
        if snap and snap.get("command") != CMD_RE.search(user_text(cmd_row)).group(1):
            snap = None
        problems = []
        rec = build(cmd_row, span, subagents, snap, problems)
        if rec is None:
            continue
        target = None
        if pending is not None and rec["id"] in pending:
            target = os.path.join(out_root, pending[rec["id"]]["target"])
        target = target or existing_dir(rec["id"], out_root)
        if target is None:
            fdir = feature_dir() if out_root == ROOT else None
            target = os.path.join(fdir, "commands") if fdir else os.path.join(out_root, "commands")
        fdir = os.path.dirname(target) if os.path.basename(os.path.dirname(os.path.dirname(target))) == "specs" else None
        if only_last:
            rec["tasks"] = task_delta((snap or {}).get("tasks"), task_state(fdir))
        title = os.path.basename(fdir) if fdir else "project level"
        if pending is None:
            upsert_jsonl(os.path.join(target, "runs.jsonl"), rec)
            upsert_log(os.path.join(target, "log.md"), rec, title)
        else:
            pending[rec["id"]] = {"target": os.path.relpath(target, out_root), "title": title, "rec": rec}
        written.append((rec, target))
    return written


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "replay":
        out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else ROOT
        for rec, target in record_transcript(sys.argv[2], out, only_last=False):
            print(f"{rec['name']} {rec['started_at']} -> {os.path.relpath(target, out)}"
                  f"{'  PROBLEMS: ' + '; '.join(rec['problems']) if rec['problems'] else ''}")
        return
    if mode == "flush":
        opt = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
        sys.exit(flush("--commit" in sys.argv, opt("--what", ""), opt("--body",
            "Published by command-log.py flush: the entries the command-log hook kept in "
            "local/command-log/ since the last flush.")))
    try:
        hook = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    if mode == "start":
        m = re.match(r"\s*(/speckit-[a-z-]+)", IDE_RE.sub("", hook.get("prompt") or ""))
        if m and hook.get("session_id"):
            fdir = feature_dir()
            write_atomic(os.path.join(START_DIR, f"{hook['session_id']}.json"), json.dumps({
                "command": m.group(1), "at": iso(dt.datetime.now(dt.timezone.utc)),
                "git_head": sh("git", "rev-parse", "--short", "HEAD").strip() or None,
                "tasks": task_state(fdir)}))
    elif mode == "stop":
        path = hook.get("transcript_path")
        if not path or not os.path.isfile(path):
            return
        with pending_lock():
            pending = read_pending()
            written = record_transcript(path, ROOT, only_last=True, pending=pending)
            write_pending(pending)
        for rec, target in written:
            if rec["problems"]:
                print(json.dumps({"systemMessage": f"command-log: {rec['name']} logged to "
                                  f"{os.path.relpath(target, ROOT)} with problems: {'; '.join(rec['problems'])}"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the session; say what failed
        print(json.dumps({"systemMessage": f"command-log failed: {type(e).__name__}: {e}"}))
